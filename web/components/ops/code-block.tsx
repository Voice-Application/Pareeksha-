"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Read-only mono block with a copy button. */
export function CodeBlock({ text, label, max = 20000 }: { text: string; label: string; max?: number }) {
  const [copied, setCopied] = useState(false);
  const [all, setAll] = useState(false);
  const shown = all || text.length <= max ? text : text.slice(0, max);
  return (
    <div className="relative rounded-sm border border-border bg-sunken">
      <pre aria-label={label} tabIndex={0} className="mono max-h-72 overflow-auto whitespace-pre-wrap break-all p-3 pr-12 text-xs">
        {shown}
      </pre>
      <Button
        icon
        variant="ghost"
        aria-label={`Copy ${label}`}
        className="absolute right-1 top-1"
        onClick={() => {
          void navigator.clipboard?.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check size={14} strokeWidth={1.6} aria-hidden /> : <Copy size={14} strokeWidth={1.6} aria-hidden />}
      </Button>
      {!all && text.length > max && (
        <button type="button" className="px-3 pb-2 text-xs text-accent-fg underline" onClick={() => setAll(true)}>
          Show all
        </button>
      )}
      <span aria-live="polite" className="sr-only">{copied ? "Copied" : ""}</span>
    </div>
  );
}

/** Single-line copyable value (URLs, one-time keys). */
export function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <input readOnly aria-label={label} value={value} onFocus={(e) => e.currentTarget.select()} className="mono h-8 min-w-0 flex-1 rounded-sm border border-border-strong bg-surface px-2 text-sm" />
      <Button
        onClick={() => {
          void navigator.clipboard?.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}
