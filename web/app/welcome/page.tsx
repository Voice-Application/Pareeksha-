import type { Metadata } from "next";
import { Landing } from "@/components/landing/landing";

export const metadata: Metadata = {
  title: "Pareeksha: crash-test your voice agent",
  description: "Synthetic Indian callers on noisy phone lines test a voice bot before launch, and every call is scored with evidence.",
};

export default function WelcomePage() {
  return <Landing />;
}
