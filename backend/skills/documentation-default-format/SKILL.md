---
name: documentation-default-format
description: Locked default format for every document the AI Documentation Generator creates, edits, expands or exports (Markdown, PDF, JPG). Documents must be well structured, aligned and plain, with NO colorization or decorative styling unless the user explicitly asks for it in chat. Use this skill whenever generating, rewriting, editing, restyling or exporting documentation, and whenever the user mentions color, heading style, font, alignment, spacing, layout, or says "change", "make it", "try another", or "keep everything else the same".
---

# Documentation Default Format

## Core principle

Every document starts as a **plain, structured, aligned document containing only the content**. Nothing is colorized, decorated or restyled unless the user explicitly asks for that exact change in chat. After a change is made, everything the user did not mention stays exactly as it was.

PRECISION > CREATIVITY. Never "improve" the look on your own.

## 1. Default presentation (applies to every new document)

Use this unless the user has given an explicit styling instruction.

- **Color:** none. All text is black on a white page. No colored headings, links, tables, borders, backgrounds, highlights, callouts or code-block shading.
- **Font:** one plain, professional font family for the whole document. No decorative fonts, no mixing families.
- **Hierarchy through size and weight only:** Title > H1 > H2 > H3 > body. Headings are bold; body is regular. Do not use size jumps larger than one step between levels.
- **Alignment:** all headings and body text left-aligned. Lists and table cells aligned consistently within each column. Never center or justify text unless asked.
- **Spacing:** one consistent gap before each heading and one consistent gap between paragraphs. No blank-line stacking, no random padding.
- **Margins and width:** uniform page margins on all sides. Content never overflows the page or is cut off.
- **Lists:** consistent bullet or number style throughout. Nested items indented one fixed step per level.
- **Tables:** plain thin black borders, bold header row, no fills, no colors. Every row has the same number of columns, and columns line up.
- **Code blocks:** plain monospace text, no syntax coloring, no shading. Keep indentation exact.
- **No extras:** no emojis, gradients, icons, shadows, watermarks or decorative separators.

## 2. Structure rules (never unstructured output)

- Output must follow a clear, ordered hierarchy: one Title, then H1 sections, then H2/H3 subsections. Never skip a level (no H3 directly under H1).
- Section order follows the project's template if one exists. If none is provided, use this default skeleton and only include sections that have real source evidence: Title → Overview → main body sections (ordered from general to specific) → validation or checklist items (if applicable) → conclusion or notes.
- Group related content under one heading. Keep each paragraph to one idea. Keep similar content in the same form (for example, all steps as one numbered list).
- Match the level of detail to the source evidence. Never pad with filler and never invent facts to fill a section.
- Do not add, remove, rename or reorder sections unless the user asks.

## 3. Permission gate for any styling

Styling (color, font, size, weight, alignment, spacing, background, borders) may change **only when the user's current chat message explicitly requests it**. Before applying:

1. Confirm the message contains an explicit styling instruction. Content requests ("add more detail", "remove this sentence") are NOT styling requests.
2. If the request is ambiguous ("make it better", "make it look nice"), do not style. Ask which element and which property, or make no style change.
3. Apply the change as a proposal when the app has an approval step, and wait for approval. Accepted changes create a new revision.
4. Never carry a color or style over into later content, new sections or regenerated documents unless the user asked for that to persist.

Regeneration, expansion or export of a document must reproduce the current approved styling exactly, and if none was approved, the plain default from Section 1.

## 4. Change-scope control

Resolve every request into three parts before touching the document:

- **TARGET:** which element (Title, H1, H2, H3, body, list, table, code block, one section, whole document).
- **CHANGE:** which single property or content action.
- **PRESERVE:** everything else.

Rules:

- A narrow request never licenses a redesign. "Make H2 green" changes the color of H2 headings only, not H1, H3, body text, links, borders, size, weight, spacing, alignment, wording or structure.
- Treat properties independently: color → color only; size → size only; bold → weight only; alignment → alignment only; spacing → spacing only; font → family only; background → background only.
- Separate content from presentation. A style request must not change wording, sections, order or technical meaning. A content request must not change color, font, alignment, spacing or layout.
- If a requested change is outside what the app supports, do not invent a new design system. Use the closest supported behavior if it clearly matches the intent, otherwise say it is unsupported.

## 5. Precedence

1. The user's request decides WHAT changes.
2. This skill decides HOW the document normally looks (the plain default).
3. App constraints decide what is technically supported.
4. Everything the user did not mention stays unchanged.

## 6. Follow-up requests

Use the recent conversation to resolve short follow-ups, but only when a styling request already exists in that conversation.

- "Try another color" / "try a darker one" / "slightly smaller" → adjust only the same element and property from the previous styling request.
- "Try" or "again" with no earlier styling request → do not style. Ask what the user wants to change.
- "Keep everything else the same" / "don't change the formatting" → apply no style changes at all.
- "Go back to plain" / "remove the color" → restore the Section 1 default for the named element, or the whole document if the user says so.

## 7. Mapping to the app's operations

Use only the existing operations: NO_CHANGE, REMOVE_TEXT, REMOVE_SECTION, REPLACE_TEXT, REWRITE_SECTION, RENAME_HEADING, ADD_AFTER, ADD_BEFORE, APPEND, REWRITE_DOCUMENT, STYLE_DOCUMENT. Choose the narrowest one that satisfies the request.

| Request | Operation |
|---|---|
| Nothing to change, or request is ambiguous styling | NO_CHANGE |
| Delete one sentence or phrase | REMOVE_TEXT |
| Delete a whole section | REMOVE_SECTION |
| Fix or swap specific wording | REPLACE_TEXT |
| Rewrite one section's content | REWRITE_SECTION |
| Rename one heading (text only) | RENAME_HEADING |
| Insert new content after / before a known spot | ADD_AFTER / ADD_BEFORE |
| Add content at the end | APPEND |
| Whole-document content expansion or restructure that the user asked for | REWRITE_DOCUMENT |
| Explicit color, font, size, alignment or spacing request | STYLE_DOCUMENT |

STYLE_DOCUMENT must touch presentation only and leave every character of content intact. Content operations must leave all existing styling intact.

## 8. Markdown and export safety

- Never break headings, lists, tables, links, code fences, blockquotes, HTML comments or metadata markers when editing.
- Keep Markdown as the source of truth. PDF and JPG exports must reproduce the same structure and the same approved styling, and must not add color on their own.
- Keep alignment in exports: no clipped text, no table columns drifting, no orphaned headings at the bottom of a page when avoidable.

## 9. Revision safety

- Every accepted change creates a new revision. Never overwrite or destroy a previous version.
- Undo and redo move between stored revisions; do not ask the model to reverse content.

## 10. Anti-drift

Do not let the document drift across revisions. Each revision must still match the plain default plus only the styling the user has explicitly approved. Never introduce on your own: decorative fonts, oversized headings, heavy weights, extra colors, gradients, boxes, icons or unusual layouts.

## 11. Reference Conformance Check (run before returning any output)

1. Structure and heading hierarchy are valid, with no skipped levels.
2. Section order is unchanged unless the user asked.
3. All text is left-aligned and consistently spaced.
4. No color or decoration exists except what the user explicitly approved.
5. Font family and sizes are consistent with the default.
6. Tables, lists and code blocks are intact and aligned.
7. Wording is unchanged for style requests; styling is unchanged for content requests.
8. Only the requested target and property differ from the previous revision.
9. Markdown is valid and no metadata was lost.

If any check fails, fix it or discard the unintended change before returning the result.

## 12. Test matrix

For each test: INPUT → TARGET → CHANGE → PRESERVED → FORBIDDEN.

| # | Input | Target / Change | Preserved | Forbidden |
|---|---|---|---|---|
| 1 | Generate docs for a ZIP, no styling words | Whole document, plain default | n/a | Any color, background, centered text, decorative font |
| 2 | "Make the headings green" | All headings, color only | Wording, size, weight, body text, tables, spacing, structure | Coloring body, links or borders; changing size or font |
| 3 | "Make H2 green" | H2 only, color only | H1, H3, body, everything else | Touching H1 or H3 |
| 4 | "Try a darker one" after test 3 | H2 color only | All else | Changing other elements or properties |
| 5 | "Try" with no earlier style request | NO_CHANGE or ask which element | Entire document | Guessing and applying a style |
| 6 | "Remove this sentence" | REMOVE_TEXT, one sentence | All formatting and other text | Restyling, rewording neighbors |
| 7 | "Rename the Overview heading to Summary" | RENAME_HEADING, text only | Level, color, spacing, content | Changing section content or order |
| 8 | "Add more detail to the install section" | REWRITE_SECTION, that section | Other sections, all styling | Adding color, new sections, reordering |
| 9 | "Make the title bigger and the headings blue" | Mixed: title size + heading color | Everything else | Changing title color or heading size |
| 10 | "Keep everything else the same" with a one-word fix | REPLACE_TEXT | All styling and structure | Any other edit |
| 11 | Regenerate after an approved green H2 | Whole document | H2 stays green, all else plain | Dropping the approved color or adding new colors |
| 12 | Export approved document to PDF/JPG | Export only | Same structure and styling as Markdown | New colors, shifted alignment, clipped tables |
| 13 | "Make it look nice" | NO_CHANGE or clarify | Entire document | Redesigning |
| 14 | Add a table of data | New table, plain borders, bold header | Rest of document | Cell fills, colored header |
