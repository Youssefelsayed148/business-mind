"use client";

import { useState } from "react";
import { Link2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { loadFacebookSdk } from "@/lib/facebookSdk";
import { useToast } from "@/components/ToastProvider";

/** Unlike WhatsApp's Embedded Signup, plain Facebook Login for Business
 * returns only an authorization `code` from FB.login() — no postMessage
 * listener needed. Which Page(s) the user granted access to is discovered
 * server-side afterward via GET /me/accounts (see facebook_oauth.py), not
 * from a client-side event. */
function runFacebookLogin(configId: string): Promise<string> {
  return new Promise((resolve, reject) => {
    window.FB?.login(
      (response) => {
        if (response.status !== "connected" || !response.authResponse?.code) {
          reject(new Error("Facebook connection was cancelled or did not complete"));
          return;
        }
        resolve(response.authResponse.code);
      },
      {
        config_id: configId,
        response_type: "code",
        override_default_response_type: true,
      },
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
      const code = await runFacebookLogin(startInfo.config_id);

      const result = await api.post<{
        connected: { page_name: string | null; page_id: string }[];
        conflicts?: { page_id: string; page_name: string | null; reason: string }[];
      }>(
        "/facebook/connect/callback",
        { code, state: startInfo.state },
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
