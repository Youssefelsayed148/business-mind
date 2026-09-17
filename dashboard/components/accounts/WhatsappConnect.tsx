"use client";

import { useState } from "react";
import { Link2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { loadFacebookSdk } from "@/lib/facebookSdk";
import { useToast } from "@/components/ToastProvider";

/** Data Embedded Signup posts back via window.postMessage once the popup
 * flow completes — separate from FB.login()'s own callback, which only
 * carries the authorization `code`. See Meta's Embedded Signup docs: the
 * event name is fixed ("WA_EMBEDDED_SIGNUP") and the payload nests
 * phone_number_id/waba_id under data.data for a "WhatsAppEmbeddedSignup"
 * message with event "FINISH" (or "FINISH_ONLY_WABA" if no number was
 * added in this pass). */
type EmbeddedSignupMessage = {
  type?: string;
  event?: string;
  data?: {
    phone_number_id?: string;
    waba_id?: string;
  };
};

type SignupResult = { code: string; phone_number_id: string; waba_id: string };

function runEmbeddedSignup(configId: string): Promise<SignupResult> {
  return new Promise((resolve, reject) => {
    let signupPayload: { phone_number_id: string; waba_id: string } | null = null;

    function onMessage(event: MessageEvent) {
      if (event.origin !== "https://www.facebook.com" && event.origin !== "https://web.facebook.com") {
        return;
      }
      try {
        const message: EmbeddedSignupMessage = JSON.parse(event.data);
        if (message.type === "WA_EMBEDDED_SIGNUP" && message.data?.phone_number_id && message.data?.waba_id) {
          signupPayload = {
            phone_number_id: message.data.phone_number_id,
            waba_id: message.data.waba_id,
          };
        }
      } catch {
        // Not JSON / not our message — other things post to window too.
      }
    }
    window.addEventListener("message", onMessage);

    window.FB?.login(
      (response) => {
        window.removeEventListener("message", onMessage);
        if (response.status !== "connected" || !response.authResponse?.code) {
          reject(new Error("WhatsApp connection was cancelled or did not complete"));
          return;
        }
        if (!signupPayload) {
          reject(new Error("Did not receive phone number details from WhatsApp Embedded Signup"));
          return;
        }
        resolve({ code: response.authResponse.code, ...signupPayload });
      },
      {
        config_id: configId,
        response_type: "code",
        override_default_response_type: true,
      },
    );
  });
}

export function WhatsappConnect({ onConnected }: { onConnected: () => void }) {
  const [connecting, setConnecting] = useState(false);
  const toast = useToast();

  async function connect() {
    setConnecting(true);
    try {
      const startInfo = await api.get<{
        app_id: string;
        config_id: string;
        graph_api_version: string;
        state: string;
      }>("/whatsapp/connect/start");

      await loadFacebookSdk(startInfo.app_id, startInfo.graph_api_version);
      const signup = await runEmbeddedSignup(startInfo.config_id);

      await api.post("/whatsapp/connect/callback", {
        code: signup.code,
        phone_number_id: signup.phone_number_id,
        waba_id: signup.waba_id,
        state: startInfo.state,
      });

      toast.success("WhatsApp number connected successfully");
      onConnected();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to connect WhatsApp number");
    } finally {
      setConnecting(false);
    }
  }

  return (
    <Button type="button" className="gap-2" onClick={connect} disabled={connecting}>
      <Link2 className="h-4 w-4" aria-hidden="true" />
      {connecting ? "Connecting..." : "Connect WhatsApp"}
    </Button>
  );
}
