import { GameRoot } from "@/components/GameRoot";

// Canonical embed entry point (doc 11 §2). The launch token arrives by postMessage or fragment.
export default function LaunchPage() {
  return <GameRoot />;
}
