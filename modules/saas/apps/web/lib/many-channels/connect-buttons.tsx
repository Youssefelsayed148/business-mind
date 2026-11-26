"use client";

import { useState } from "react";

import { manyRequest, type ManyScope } from "@/lib/many";
import { Button } from "@/lib/ui";

import { loadMetaSdk } from "./meta-sdk";

export type ChannelNote = { tone: "info" | "error"; text: string };

interface StartInfo {
  app_id: string;
  config_id: string;
  graph_api_version: string;
  state: string;
}

/**
 * Plain Facebook Login for Business returns a user access token from FB.login(). (Asking
 * for a `code` instead breaks: it is bound to the SDK's own redirect_uri.) Many checks the
 * token was issued to its app and finds the Pages through GET /me/accounts afterwards.
 */
function runFacebookLogin(configId: string): Promise<string> {
  return new Promise((resolve, reject) => {
    window.FB?.login(
      (response) => {
        const accessToken = response.authResponse?.accessToken;
        if (response.status !== "connected" || !accessToken) {
          reject(
            new Error("Facebook connection was cancelled or did not complete."),
          );
          return;
        }
        resolve(accessToken);
      },
      { config_id: configId },
    );
  });
}

interface EmbeddedSignupMessage {
  type?: string;
  data?: { phone_number_id?: string; waba_id?: string };
}
interface SignupResult {
  code: string;
  phone_number_id: string;
  waba_id: string;
}

/** Origins Meta posts the Embedded Signup result from. Anything else is ignored. */
export function isMetaOrigin(origin: string): boolean {
  return (
    origin === "https://www.facebook.com" ||
    origin === "https://web.facebook.com"
  );
}

/**
 * WhatsApp Embedded Signup. The phone number and WhatsApp business account arrive through
 * window.postMessage (event type WA_EMBEDDED_SIGNUP); FB.login() itself only carries the
 * authorization `code`.
 */
function runEmbeddedSignup(configId: string): Promise<SignupResult> {
  return new Promise((resolve, reject) => {
    let payload: { phone_number_id: string; waba_id: string } | null = null;
    function onMessage(event: MessageEvent) {
      if (!isMetaOrigin(event.origin)) return;
      try {
        const message: EmbeddedSignupMessage = JSON.parse(event.data);
        if (
          message.type === "WA_EMBEDDED_SIGNUP" &&
          message.data?.phone_number_id &&
          message.data?.waba_id
        ) {
          payload = {
            phone_number_id: message.data.phone_number_id,
            waba_id: message.data.waba_id,
          };
        }
      } catch {
        // Not JSON, not ours: other things post to the window too.
      }
    }
    window.addEventListener("message", onMessage);
    window.FB?.login(
      (response) => {
        window.removeEventListener("message", onMessage);
        if (response.status !== "connected" || !response.authResponse?.code) {
          reject(
            new Error("WhatsApp connection was cancelled or did not complete."),
          );
          return;
        }
        if (!payload) {
          reject(
            new Error(
              "Did not receive the phone number details from WhatsApp signup.",
            ),
          );
          return;
        }
        resolve({ code: response.authResponse.code, ...payload });
      },
      {
        config_id: configId,
        response_type: "code",
        override_default_response_type: true,
      },
    );
  });
}

function errorText(caught: unknown, fallback: string): string {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

export function FacebookConnect({
  scope,
  onConnected,
  onNote,
}: {
  scope: ManyScope;
  onConnected: () => void;
  onNote: (note: ChannelNote) => void;
}) {
  const [connecting, setConnecting] = useState(false);

  async function connect() {
    setConnecting(true);
    try {
      const start = await manyRequest<StartInfo>(
        scope,
        "GET",
        "facebook/connect/start",
      );
      await loadMetaSdk(start.app_id, start.graph_api_version);
      const accessToken = await runFacebookLogin(start.config_id);
      const result = await manyRequest<{
        connected: { page_name: string | null; page_id: string }[];
        conflicts?: { page_id: string }[];
      }>(scope, "POST", "facebook/connect/callback", {
        access_token: accessToken,
        state: start.state,
      });
      const count = result.connected.length;
      const conflicts = result.conflicts?.length ?? 0;
      let text =
        count === 1
          ? "Facebook Page connected."
          : `${count} Facebook Pages connected.`;
      if (conflicts) {
        text += ` ${conflicts} Page${conflicts === 1 ? " is" : "s are"} already connected to a different workspace and ${conflicts === 1 ? "was" : "were"} not connected here.`;
      }
      onNote({ tone: "info", text });
      onConnected();
    } catch (caught) {
      onNote({
        tone: "error",
        text: errorText(caught, "Could not connect the Facebook Page."),
      });
    } finally {
      setConnecting(false);
    }
  }

  return (
    <Button
      data-testid="connect-facebook"
      disabled={connecting}
      onClick={() => void connect()}
    >
      {connecting ? "Connecting..." : "Connect Facebook Page"}
    </Button>
  );
}

export function WhatsappConnect({
  scope,
  onConnected,
  onNote,
}: {
  scope: ManyScope;
  onConnected: () => void;
  onNote: (note: ChannelNote) => void;
}) {
  const [connecting, setConnecting] = useState(false);

  async function connect() {
    setConnecting(true);
    try {
      const start = await manyRequest<StartInfo>(
        scope,
        "GET",
        "whatsapp/connect/start",
      );
      await loadMetaSdk(start.app_id, start.graph_api_version);
      const signup = await runEmbeddedSignup(start.config_id);
      await manyRequest(scope, "POST", "whatsapp/connect/callback", {
        code: signup.code,
        phone_number_id: signup.phone_number_id,
        waba_id: signup.waba_id,
        state: start.state,
      });
      onNote({ tone: "info", text: "WhatsApp number connected." });
      onConnected();
    } catch (caught) {
      onNote({
        tone: "error",
        text: errorText(caught, "Could not connect the WhatsApp number."),
      });
    } finally {
      setConnecting(false);
    }
  }

  return (
    <Button
      data-testid="connect-whatsapp"
      disabled={connecting}
      onClick={() => void connect()}
    >
      {connecting ? "Connecting..." : "Connect WhatsApp"}
    </Button>
  );
}
