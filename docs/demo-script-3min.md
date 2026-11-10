# Pareeksha 3-minute demo script

Full-feature version of [demo-script.md](demo-script.md) (60 s). Target runtime 180 s. Voice-over is paced at about
2 words per second. Labels in **bold** are the exact sidebar and button names in the web app.

## 0. Before recording (not on camera)

Stack up and seeded as in [Guide 1](guides/01-quickstart.md). Gnani allows one request per key, so every result below
is pre-run and the recording only clicks through finished results.

1. Failing run: mock agent with `MOCK_BUGS=no_amount_confirm`, "EMI Reminder Bot" x "Promise to pay on Friday" x
   "Manju — auto driver" x `pstn_8k_alaw`.
2. Passing run: the same against the clean mock agent (for **Run compare** and **Regression**).
3. One finished quick test under **Test my prompt**, with a second prompt version so the comparison shows.
4. One knowledge base under **Documents** with questions, and one finished matrix under **RAG lab**.
5. The Vaani dialect report under **Dialect** (`proof/DIALECT-02`).
6. One finished audit under **Audits**.
7. Optional, only if they exist for real: the HubSpot note and the two GitHub PR checks (red and green).

## 1. Shot list (180 s)

| t (s) | Screen and action | Voice-over |
|---|---|---|
| 0 to 12 | Title card, then **Home** | "Voice bots sound perfect in a demo. Then a real Indian caller rings from a noisy street, mixing Kannada and English, and the bot breaks. Pareeksha finds that before launch." |
| 12 to 24 | **Agents**, open "EMI Reminder Bot" | "Connect any voice agent: a Pipecat bot, or anything that speaks our open audio protocol. This one is a loan reminder bot." |
| 24 to 38 | **Personas**, then **Noise profiles**, play one noisy sample | "Then pick who calls it. Twenty Indian personas, like Manju, an auto driver who speaks Kannada. And real line conditions: 8 kHz phone audio, office babble, street and market noise." |
| 38 to 50 | **Scenarios**, then **Test designer** | "Scenarios describe what the caller wants. Write them by hand, or build the test in a chat with the test designer." |
| 50 to 64 | **New run** wizard, then **Results**, open the failing run, show pass rate and heatmap | "Start a run. Every caller voice is Gnani Timbre text to speech, and the call is transcribed by Gnani Prisma speech to text. Here is the result, call by call." |
| 64 to 84 | Click the red cell to open the call page. Click the evidence turn, the waveform seeks, press play | "This call failed. The caller promised four thousand rupees and the bot never confirmed the amount. You get the recording, the transcript, and the exact turn the judge cites as evidence. Nothing is a bare score." |
| 84 to 96 | **Promote to regression**, then **Run compare** with the passing run | "One click makes it a permanent regression test. Fix the bot, run again, and compare: red turns green." |
| 96 to 112 | **Dialect**, open the Vaani report, point at the weakest cell | "The dialect report runs real Kannada and Hindi clips through speech recognition under clean, phone and noisy audio, and shows where accuracy drops, with sample sizes." |
| 112 to 126 | **Audits**, **Upload recording**, cut to the finished audit | "After launch, the same judge audits real recordings. Upload a call or send it by signed webhook, and it flags what went wrong." |
| 126 to 140 | **Test my prompt**, open the finished test, show "Compared with the earlier prompt" | "No voice bot yet? Test just the prompt. Typed conversations run against it, and you see what a prompt change fixed and what it broke." |
| 140 to 154 | **Documents**, open the knowledge base, then **RAG lab**, open the matrix report | "Upload your documents, generate questions with known answers, and the RAG lab compares retrieval setups side by side on hit rate, hallucinations and cost." |
| 154 to 166 | **Integrations** (delivery log), then terminal: `pareeksha run ... --wait`. Optional: HubSpot note, GitHub PR check | "Scores flow out to HubSpot and webhooks. And with the CLI and GitHub Action, a pull request fails until the bug is fixed." |
| 166 to 174 | **Calibration** | "The judge is an LLM, so we measure it against human labels and show that openly. Read the evidence, not just the score." |
| 174 to 180 | End card: name, repo link, "Built on Gnani Prisma and Timbre" | "Pareeksha. Crash-test your voice agent the way India actually talks." |

## 2. Honesty rules

- Say the real pass rate of the real run. Do not quote design targets.
- Do not claim judge accuracy. Agreement with human labels is below target (`proof/EVAL-06/calibration.md`).
- Dialect numbers come from 110 Vaani clips; the sample is small and Kannada WER is inflated by colloquial spellings.
- Show the HubSpot note and the GitHub checks only if they were produced for real. Otherwise show the
  **Integrations** delivery log and the CLI, and drop the words "HubSpot" and "pull request" from that line.
- Name only the Gnani models actually used: Prisma (speech to text) and Timbre (text to speech). The caller brain and
  judge run on DeepSeek, not Evon.
- No keys on screen.
