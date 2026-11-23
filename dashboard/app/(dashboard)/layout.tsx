import { AuthGate } from "@/components/layout/AuthGate";
import { ErrorBoundary } from "@/components/ErrorBoundary";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <AuthGate><ErrorBoundary>{children}</ErrorBoundary></AuthGate>;
}
