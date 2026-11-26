/**
 * The Meta (Facebook) JavaScript SDK, loaded only when a person clicks Connect.
 *
 * Ported from the old dashboard (lib/facebookSdk.ts). The app id and Graph version come from
 * Many's `connect/start` answer at click time; nothing is baked into this repository.
 * Facebook Page login and WhatsApp Embedded Signup share one script and one `fbAsyncInit`
 * hook, so there is a single module-scoped load promise.
 */

declare global {
  interface Window {
    FB?: {
      init: (config: {
        appId: string;
        version: string;
        xfbml?: boolean;
      }) => void;
      login: (
        callback: (response: {
          authResponse?: { code?: string; accessToken?: string } | null;
          status?: string;
        }) => void,
        options: {
          config_id: string;
          response_type?: string;
          override_default_response_type?: boolean;
        },
      ) => void;
    };
    fbAsyncInit?: () => void;
  }
}

export const META_SDK_URL = "https://connect.facebook.net/en_US/sdk.js";

let loadPromise: Promise<void> | null = null;

export function loadMetaSdk(
  appId: string,
  graphApiVersion: string,
): Promise<void> {
  if (window.FB) return Promise.resolve();
  if (loadPromise) return loadPromise;
  loadPromise = new Promise<void>((resolve, reject) => {
    window.fbAsyncInit = () => {
      window.FB?.init({ appId, version: graphApiVersion, xfbml: false });
      resolve();
    };
    const script = document.createElement("script");
    script.src = META_SDK_URL;
    script.async = true;
    script.defer = true;
    script.onerror = () => {
      // Let the next click try again.
      loadPromise = null;
      reject(new Error("Could not load the Facebook SDK. Try again."));
    };
    document.body.appendChild(script);
  });
  return loadPromise;
}
