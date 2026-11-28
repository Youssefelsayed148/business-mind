import Link from "next/link";

import { Notice } from "@/lib/ui";

/** Old Many dashboard address whose new page is not built yet (Phase 4B, decision P6). */
export default async function MovedPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string | string[] }>;
}) {
  const { from } = await searchParams;
  const where = typeof from === "string" ? from.slice(0, 80) : "";
  return (
    <main className="workspace-content" id="main">
      <h1>This page has moved</h1>
      <Notice
        scope="item"
        message={`The address ${where || "you opened"} belongs to the earlier Many dashboard. It is being rebuilt in the new workspace and is not available here yet.`}
      />
      <p>
        <Link href="/app">Go to your workspaces</Link>
      </p>
    </main>
  );
}
