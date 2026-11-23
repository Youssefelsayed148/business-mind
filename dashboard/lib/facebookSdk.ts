declare global {
  interface Window {
    FB?: {
      init: (config: { appId: string; version: string; xfbml?: boolean }) => void;
      login: (
        callback: (
          response: { authResponse?: { code?: string; accessToken?: string } | null; status?: string },
        ) => void,
        options: { config_id: string; response_type?: string; override_default_response_type?: boolean },
      ) => void;
    };
    fbAsyncInit?: () => void;
  }
}

// Shared by FacebookConnect and WhatsappConnect, which can both be mounted
// on the Accounts page at once. Both ride the same Facebook JS SDK script
// and the same global window.fbAsyncInit hook, so a single module-scoped
// promise/loader is required -- two independent copies (one per component)
// would each overwrite the other's fbAsyncInit if both were clicked before
// the script finished loading, permanently hanging whichever click lost.
let fbSdkLoadPromise: Promise<void> | null = null;

export function loadFacebookSdk(appId: string, graphApiVersion: string): Promise<void> {
  if (window.FB) return Promise.resolve();
  if (fbSdkLoadPromise) return fbSdkLoadPromise;

  fbSdkLoadPromise = new Promise((resolve, reject) => {
    window.fbAsyncInit = () => {
      window.FB?.init({ appId, version: graphApiVersion, xfbml: false });
      resolve();
    };
    const script = document.createElement("script");
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.defer = true;
    script.onerror = () => reject(new Error("Failed to load the Facebook SDK"));
    document.body.appendChild(script);
  });
  return fbSdkLoadPromise;
}
