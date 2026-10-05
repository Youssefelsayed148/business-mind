"use client";

import { useState } from "react";
import { Link2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { loadFacebookSdk } from "@/lib/facebookSdk";
import { useToast } from "@/components/ToastProvider";

/** Unlike WhatsApp's Embedded Signup, plain Facebook Login for Business
 * returns a user access token from FB.login() — no postMessage listener
 * needed. (Requesting a `code` instead breaks: it's bound to the SDK's
 * internal redirect_uri and can't be exchanged server-side.) The backend
 * verifies the token was issued to our app before using it. Which Page(s)
 * the user granted access to is discovered server-side afterward via
 * GET /me/accounts (see facebook_oauth.py), not from a client-side event. */
function runFacebookLogin(configId: string): Promise<string> {
  return new Promise((resolve, reject) => {
    window.FB?.login(
      (response) => {
        const accessToken = response.authResponse?.accessToken;
        if (response.status !== "connected" || !accessToken) {
          reject(new Error("Facebook connection was cancelled or did not complete"));
          return;
        }
        resolve(accessToken);
      },
      { config_id: configId },
    );
  });
}

export function FacebookConnect({ onConnected }: { onConnected: () => void }) {
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
      }>("/facebook/connect/start");

      await loadFacebookSdk(startInfo.app_id, startInfo.graph_api_version);
      const accessToken = await runFacebookLogin(startInfo.config_id);

      const result = await api.post<{
        connected: { page_name: string | null; page_id: string }[];
        conflicts?: { page_id: string; page_name: string | null; reason: string }[];
      }>(
        "/facebook/connect/callback",
        { access_token: accessToken, state: startInfo.state },
      );

      const count = result.connected.length;
      if (count === 1) {
        toast.success("Facebook Page connected successfully");
      } else {
        toast.success(`${count} Facebook Pages connected successfully`);
      }
      if (result.conflicts?.length) {
        toast.warning(
          result.conflicts.length === 1
            ? "1 Facebook Page is already connected to a different workspace and was not connected here."
            : `${result.conflicts.length} Facebook Pages are already connected to a different workspace and were not connected here.`,
        );
      }
      onConnected();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to connect Facebook Page");
    } finally {
      setConnecting(false);
    }
  }

  return (
    <Button type="button" className="gap-2" onClick={connect} disabled={connecting}>
      <Link2 className="h-4 w-4" aria-hidden="true" />
      {connecting ? "Connecting..." : "Connect Facebook Page"}
    </Button>
  );
}
