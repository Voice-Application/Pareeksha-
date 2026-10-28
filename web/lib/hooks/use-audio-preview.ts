"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/call";

export type AudioState = "idle" | "loading" | "playing" | "paused" | "error";

// Only one preview plays at a time across the page (personas spec).
let stopActive: (() => void) | null = null;

/**
 * Fetches audio on first play, caches the blob URL for the same `cacheKey`, and plays it.
 * Changing `cacheKey` (for example after the persona is edited) drops the cached clip.
 */
export function useAudioPreview(load: () => Promise<Blob>, cacheKey: string) {
  const [state, setState] = useState<AudioState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const url = useRef<{ key: string; href: string } | null>(null);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  const stop = useCallback(() => {
    audio.current?.pause();
    if (audio.current) audio.current.currentTime = 0;
    setState((s) => (s === "playing" || s === "paused" ? "idle" : s));
  }, []);

  useEffect(() => {
    return () => {
      audio.current?.pause();
      if (url.current) URL.revokeObjectURL(url.current.href);
      if (stopActive === stop) stopActive = null;
    };
  }, [stop]);

  useEffect(() => {
    if (url.current && url.current.key !== cacheKey) {
      audio.current?.pause();
      URL.revokeObjectURL(url.current.href);
      url.current = null;
      setDuration(null);
      setState("idle");
    }
  }, [cacheKey]);

  const toggle = useCallback(async () => {
    if (state === "playing") {
      audio.current?.pause();
      setState("paused");
      return;
    }
    if (state === "loading") return;
    setError(null);
    if (stopActive && stopActive !== stop) stopActive();
    try {
      if (!url.current || url.current.key !== cacheKey) {
        setState("loading");
        const blob = await loadRef.current();
        if (url.current) URL.revokeObjectURL(url.current.href);
        url.current = { key: cacheKey, href: URL.createObjectURL(blob) };
        audio.current = new Audio(url.current.href);
        audio.current.onloadedmetadata = () => setDuration(Number.isFinite(audio.current?.duration) ? (audio.current?.duration ?? null) : null);
        audio.current.onended = () => setState("idle");
      }
      stopActive = stop;
      await audio.current!.play();
      setState("playing");
    } catch (e) {
      setState("error");
      setError(e instanceof ApiError ? e.userMessage() : e instanceof Error && e.name === "NotAllowedError" ? "The browser blocked playback." : "The clip could not be played.");
    }
  }, [state, cacheKey, stop]);

  return { state, error, duration, toggle, stop };
}
