# 17. API keys  `/api-keys`

Requirements: FR-DX-2, FR-DB-5 (Must). Purpose: create and revoke keys for the SDK, CLI and GitHub Action. A full key is shown once, here, and nowhere else in the product. Note: this page is the only place where a secret exists in the browser, and only briefly.

## Layout

```
EYEBROW  3 active keys
TITLE    API keys                                                    [Create key]
         Use a key with the SDK, the CLI or the GitHub Action. The key is shown once.
+-- DataTable ---------------------------------------------------------------------------+
| Name              Prefix              Scopes                     Last used    Created      |
| github-actions    pk_live_ab12cd34    read, runs:write           2 h ago      12 Oct   [...] |
| demo (seed)       pk_live_9f0e8d7c    admin                      never        10 Oct   [...] |
+---------------------------------------------------------------------------------------+
+-- Panel: How to use (CodeBlock) --------------------------------------------------------+
| pareeksha login --key pk_live_...   |   export PAREEKSHA_API_KEY=...                       |
+--------------------------------------------------------------------------------------+
```
- Scopes shown as neutral mono chips; `admin` chip has a triangle icon and tooltip "Full access".
- Seed/demo key carries a `demo` chip and a note "Created by make demo. Revoke before sharing the instance."
- Row menu: Revoke (ConfirmDialog naming the key, stating "Anything using it stops working immediately."). A revoked key disappears from the active list and shows under a `Revoked` filter with date.

## Create key (Dialog 480px)
Fields: name (required, hint "Where will this be used? For example github-actions"), scopes as checkboxes with descriptions (`read` Read data; `runs:write` Create and cancel runs; `audits:write` Upload and audit calls; `admin` Everything, including API keys and the DLQ; checking `admin` checks and locks the rest). Footer `Create key`.

**One-time reveal:** the same Dialog becomes the reveal view: the full key in a `CopyField` (mono, 16px, selectable), a prominent neutral strip "This is the only time you will see this key. Store it in a secret manager.", and a required checkbox "I have copied the key" enabling `Done`. Esc and backdrop do not close the reveal. On close the key is removed from component state, never written to storage or URL, and not included in any toast.

## Components
`PageHeader`, `DataTable`, `Dialog` (create and reveal), checkbox group, `CopyField`, `ConfirmDialog`, `CodeBlock`, `Button`, `Toast`.

## Data
`GET /api-keys` (prefix, scopes, last_used_at), `POST /api-keys` (returns `key` once), `DELETE /api-keys/{id}`. Requires the `admin` scope to manage keys; with lower scope the page is read-only and says so.

## States
- **Empty:** "No API keys yet. Create one to use the SDK, CLI or GitHub Action." Primary `Create key`. (A freshly seeded instance has the demo key, so this appears only after revoking all.)
- **Loading:** 3 skeleton rows.
- **Error:** list standard; create failure (validation, duplicate name) shows field errors in the Dialog and keeps its values; network failure after the server created the key is the dangerous case: if the response is lost the UI says "We could not confirm the key was created. Check the list before trying again" and refreshes the list to avoid duplicates.
- **Revoke errors:** 404 treated as already revoked; 5xx Toast with Retry.
- **Scope missing:** whole page read-only; `Create key` and `Revoke` disabled with tooltip "Needs the admin scope".
- **Never:** show a full key in a table, a log, a URL, or after the reveal Dialog closes. QA checks the DOM and network responses after closing (FR-DB-5).
