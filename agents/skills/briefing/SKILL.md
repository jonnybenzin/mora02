---
name: briefing
description: Use this whenever someone wants a briefing written, wants to brief you on a job, asks you to work out what exactly should be researched or made, or describes something they want without saying it precisely. Covers research briefs and creative briefs. It is the two-pass method — gather first, then check the structure for gaps — and it names where the questions and the target format live.
---

# Writing a briefing

Two passes, deliberately separate. Leading a conversation and auditing a
document are different jobs, and doing both at once is how a briefing ends up
feeling complete while three fields are empty.

## First: which kind of briefing

Two kinds live here, each with its own folder:

| Folder | For |
|---|---|
| `research/` | finding something out — "what is there on", "compare these", "is X worth it" |
| `creative/` | making something — image, video, text, campaign |

**This is the opening move.** Before anything else, ask which of the two it is
— plainly, in one sentence: *"What kind of brief do you need — a research
brief or a creative brief?"* Not a menu, not an explanation of the difference
unless asked.

Asking first rather than inferring is deliberate. The two catalogues share
almost no questions, so guessing wrong costs the whole first pass — and a person
who is told the shape at the start knows where the conversation is going.

The one exception: if the request already says which, do not ask again. Name it
back in three words and start (*"Research brief, got it."*). Asking
about something someone just said reads as not having listened.

Everything below then reads `QUESTIONS.md` and `TEMPLATE.md` **from that folder**.

If neither fits, say so and use `research/` as the closer of the two rather
than inventing a third. A briefing in the wrong shape is still worth more than
an unstructured conversation, and the gap becomes visible material for a folder
that should exist.

## Pass one — gather

Read `QUESTIONS.md` from the folder you chose. Work through it in order, **one question per turn**, in your
own words rather than reading it aloud. React to each answer before moving on:
if it is thin, ask once more, smaller. If the second attempt brings nothing, note
it as open and continue.

Skip a question that an earlier answer already covered. Nobody wants to be asked
twice, and asking anyway reads as not having listened.

**Offer the short way out early.** Once the first two questions are answered —
what they want to know and what hangs on it — offer to stop. A long
questionnaire in front of a cheap answer costs more than it saves, and the
person is the only one who knows which of the two this is.

Offer it as two real options, not as "everything or nothing":

> *"I can go through the remaining questions — or I can fill in what already
> follows from your request, mark that as an assumption, and only ask about
> what I genuinely cannot know. Which would you prefer?"*

## Three states, not two

This is what makes the short path worth taking. Every field of the template is
in exactly one of three states, and they must be told apart:

| Zustand | Wann | Wie es im Dokument steht |
|---|---|---|
| **beantwortet** | jemand hat es gesagt | der Wert |
| **angenommen** | folgt aus der Frage oder dem Zweck | der Wert, dazu `(angenommen)` |
| **offen** | folgt aus nichts und wurde nicht gesagt | `offen` |

**Derive what follows.** A question about the best self-hosted open-weight video
models already contains its search angles, already rules out closed APIs, and
already implies that a three-year-old answer is worthless. Writing `offen` there
is not caution, it is refusing to read the question. Whoever executes the brief
would have to make the same inference anyway — unwritten, unchecked, and
invisible.

**Mark it, always.** An assumption written as a fact is the invention this whole
skill exists to prevent. Written as an assumption it is the opposite: something
the person corrects in five seconds by glancing at a list.

**The line between the two runs through the subject, not through convenience.**

- What follows from the SUBJECT may be assumed: search angles, what is out of
  scope, how current an answer has to be, what shape the result takes. These are
  properties of the question, and anyone reading it would derive the same.
- What only the ASKER can know may never be assumed: how deep they want to go
  when the question does not say, what convinces them, and **when they would
  call it enough**.

`Abbruchkriterium` is the hard case and the one that keeps slipping. It is not a
fact about the subject — it is this person's judgement of sufficiency, and there
is nothing to derive it from. Writing *„beendet, wenn eine klare Empfehlung
vorliegt"* sounds like a criterion and is a tautology: it says the research ends
when it has succeeded. Measured: this field was correctly left open, and then
invented one round later, after the pressure to derive was tightened. **It stays
`offen` unless the person said it.**

That is why a short brief has one or two open fields, not nine — and not zero.
A brief with nothing open has stopped distinguishing what it was told from what
it worked out.

## The document follows the template, not the catalogue

Write the sections `TEMPLATE.md` names, in its order and under its headings. The
catalogue is how you ASK; the template is what you HAND OVER, and the two are
not the same shape. `Assumed` and `Open` are sections of their own — an
assumption inlined behind a value and nowhere else is one nobody scans for.

Stop when the catalogue is done, or when the person says that is enough.

## Pass two — check

**Say that you are doing it.** One short line — *"Let me run through the
template quickly and see if anything is missing."* — and then do it. This is not decoration: without a
spoken transition the second pass gets skipped, and the document is written
straight from the conversation. Measured, on the first real briefing this skill
ever produced: nine of eleven questions asked, no second pass, and the two
fields that carry the most weight came out thin.

**Read `TEMPLATE.md` again now**, from the same folder, rather than working from
what you remember of it. Then go through it **field by field**, against everything
you have been told. For each field there are exactly three outcomes:

- it is answered → carry it over
- it is **thin** — a word where a sentence is needed, an answer that fits any
  project — → ask about this one field, specifically
- it is untouched → ask about it, once

Two fields are never allowed to pass as thin, because whoever executes the brief
will act on them:

- **Sources** — "anything", "doesn't matter" and "whatever you find" are not
  answers. Ask the question from the other side: *"What would NOT convince
  you?"* A person who cannot name what counts can almost always name what does
  not.
- **Shape of the result** — on the LONG path, ask; and when a table or comparison is
  wanted, ask which columns. On the SHORT path, derive it and mark it: what
  someone wants out of a comparison follows from what they are deciding, and
  columns follow from the subject. Leaving the whole field `offen` while being
  able to list the candidates in the gap section is the worst of both — it
  neither asked nor decided.

  The rule against inventing columns is about *how they are written down*, not
  about whether they may be derived. `(angenommen)` plus a line in the
  assumptions list is correctable in five seconds; the same columns written as
  agreed are not.

Ask these in one short block, not one per turn: at this point the person can see
the end and would rather answer four things than sit through four rounds.

This pass is what the whole method is for. The gaps a briefing dies of are not
the questions nobody asked — they are the ones that got an answer which said
nothing.

## Then hand it over

Fill `TEMPLATE.md` and give it back as text. Every field that stayed open says
`open` — not a guess, not a plausible placeholder, not an average value. A
visible gap costs a follow-up question; an invented answer costs a production
run.

Below the document, name what is open in one line, so the person sees it without
reading the whole thing again.

## Where the files live

`QUESTIONS.md` and `TEMPLATE.md` sit in the kind's folder beside this file. Read
them each time rather than reciting them from memory — they get edited, and an
edit that never reaches a conversation is worse than no edit at all.

They are meant to be rewritten as real briefings show what is missing. Say so if
someone asks: the creative catalogue in particular is generic on purpose, not by
neglect.

## What a research briefing is for

It is not a document that gets filed. It is the **order** somebody else works
from — a person, or an agent that searches and reads. Two of its fields carry
that weight: *Quellen* settles every later argument about whether an answer is
any good, and *Abbruchkriterium* is the difference between an order and a wish.

That is also why a gap here costs more than elsewhere. Whoever executes the
brief will fill an empty field with a guess, and a guessed source criterion
produces a research result that looks finished and answers a different
question.
