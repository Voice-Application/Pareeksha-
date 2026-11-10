# Pareeksha: test your voice and chat bots before your customers do

**Built on Gnani Prisma (speech to text) and Gnani Timbre (text to speech).** Open source, and it runs on your own machine.

## The problem

Indian banks, lenders and service companies are putting voice bots on the phone with real customers. These customers speak Kannada, Hindi, English and mixes of all three, often over 8 kHz phone lines with traffic in the background. Teams usually find out what goes wrong from complaints: a bot that ignores a disputed charge, shares loan details before checking identity, promises a fee waiver it cannot give, or makes up answers that are not in its documents. Manual QA covers a handful of calls. Generic eval tools are text-only and English-first.

## The solution

Pareeksha (Sanskrit for "examination") is a test bench that phones your bot the way your customers would, then tells you exactly what broke and where.

- **Test a prompt.** Paste a system prompt and some made-up customer data. Pareeksha pulls out the rules, writes normal and tricky customers to test each one, and shows every broken rule with the exact line in the conversation. One click rewrites the prompt and tests it again.
- **Voice callers.** Synthetic Kannada, Hindi and English personas, voiced by **Gnani Timbre**, call your bot.
- **Noisy phone lines.** Noise profiles set the codec (8 kHz A-law PSTN), packet loss, background noise and SNR, all the way down to an auto-rickshaw at 0 dB.
- **Every call judged.** Each call is transcribed by **Gnani Prisma** and scored by an LLM judge on task completion, policy compliance, factual accuracy, language handling, empathy, flow and escalation. Every score comes with a written reason and links to the turns behind it.
- **RAG lab.** Before adding RAG, it runs the same questions with no RAG, with the full document in the prompt, and with each retrieval setup. It reports hallucination rate, hit rate, latency and monthly cost, then recommends the setup to ship. In our demo: 75% hallucination without RAG versus 0% with hybrid search + rerank, at about 61% less cost than putting the full document in the prompt (small demo knowledge base, 14 questions).
- **Dialect report.** Runs regional speech through Gnani Prisma on clean, phone and noisy lines, and shows a WER/CER heatmap with the sample size on every cell, plus the words it mishears most.
- **Regression and compare.** One click turns a failed call into a permanent regression test, and run compare shows exactly which callers and lines got worse after a prompt change.
- **Ask Pareeksha.** An assistant on every page that knows your tests and can start one for you.

## How Gnani is used

| Gnani model | Where it is used in Pareeksha |
|---|---|
| **Timbre** (`timbre-v3.0`) | Voices every synthetic caller persona, in Kannada, Hindi and English |
| **Prisma** (speech to text) | Transcribes every call before judging, and is the engine measured in the dialect report |

## Who it is for

Teams that build or buy voice and chat bots for Indian customers: banks and NBFCs, collections, insurance, telecom and customer support. They get a repeatable, multilingual check before every prompt change ships.

## Status

v1.0.0, open source. Python/FastAPI backend, Kafka workers, Postgres, Next.js web app, Docker Compose setup, and a bundled mock voice bot with planted bugs for demos. All data in the demo is synthetic.

**Demo video:** 3-minute walkthrough recorded live from the app.
