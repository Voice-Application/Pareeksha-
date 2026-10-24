/** Display helpers shared by the list pages. */

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];
const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function relativeTime(iso: string, now = Date.now()): string {
  const secs = Math.round((new Date(iso).getTime() - now) / 1000);
  for (const [unit, size] of UNITS) {
    if (Math.abs(secs) >= size) return rtf.format(Math.round(secs / size), unit);
  }
  return "just now";
}

export const LANGUAGE_LABEL: Record<string, string> = { "kn-IN": "Kannada", "hi-IN": "Hindi", "en-IN": "English" };
export const LANGUAGES = ["kn-IN", "hi-IN", "en-IN"] as const;

/** Timbre v3.0 stock voices (TRD 77). */
export const VOICES = ["Avinash", "Shivani", "Lakshmi", "Kalpana", "Shubham", "Prakash", "Devansh", "Yashraj", "Chetana", "Vasudha", "Riyaa", "Tarika", "Harshad"];

/** Plain-language fix per test-connection error word (agents spec: fixed dictionary). */
export const CONNECTION_FIX: Record<string, string> = {
  dns: "Check the host name in the endpoint URL.",
  refused: "Nothing is listening on that port. Start the agent or fix the port.",
  timeout: "The agent did not speak within 10 seconds. Check that it greets the caller on connect.",
  protocol: "The agent answered, but not with the pareeksha-audio-v1 protocol. Check the adapter setting.",
};

export const SILENCE_LABEL: Record<string, string> = { normal: "Normal", long_pauses: "Long pauses", goes_silent: "Goes silent" };
export const INTERRUPT_LABEL = ["Never", "Rarely", "Often", "Constantly"];
