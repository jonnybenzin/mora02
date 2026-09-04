---
name: recherche
description: Use this whenever someone asks you to find something out, wants to know what exists on a subject, asks you to compare options, asks whether something is worth it, or hands you a research briefing. It is the method — work out the order yourself, search broad, read, weigh, search again — and it says when to stop.
---

# Doing a piece of research

Five moves. The first is the one people skip. The two that decide whether an
answer can be acted on are the least glamorous: taking notes while you read,
and checking the load-bearing facts at their source.

## 1. Work out the order — yourself

Do not interview anyone. Take the question, derive what follows from it, say in
**three lines** what you assumed, and start. The person corrects you if
something is wrong; that costs them one sentence instead of eleven answers.

What to settle before searching, most of it derivable from the question itself:

| | |
|---|---|
| **Angles** | which wordings, synonyms, English terms, vendor names, opposing views |
| **Boundary** | what is *not* being asked — usually implied by the question |
| **Currency** | how old an answer may be. "currently best" means recent; a definition does not |
| **Form** | what the answer should look like, which follows from what is being decided |
| **Constraints** | the hard constraint the answer must fit — budget, hardware, region, language |

The frame is the one worth a question if you cannot derive it, because it sieves
harder than any judgement of quality: an option that does not fit is not an
option, however good it is.

Two things you can never derive and must not invent: **what counts as a source
for this person**, and **when they would call it enough**. Work with your own
defaults, say that you did, and let them be corrected.

If you were handed a **briefing** instead of a bare question, read it and use it
as the order. Its `Angenommen` section is someone else's derivation — treat it
as given. Its `Offen` fields are yours to decide, and to declare.

## 2. Search broad, read, and take notes

Ask **several angles in one call**, not one after another. Different wordings
reach different corners of a subject, and one call returning two dozen results
is worth more than six calls returning four each — each extra round is another
chance to lose the thread.

Vary deliberately: the plain phrasing, the technical term, the English term, a
likely vendor or project name, and the question a sceptic would ask.

Then read the promising ones, **several at once**. Judge from titles and
snippets which are worth opening; do not open everything.

**Take notes as you read, not afterwards — with the `note` tool.** One call
after each round of reading, carrying **all** findings from it as a list, while
the pages are still in front of you and before you open more. Each note carries
three things:

- **claim** — what the source says about your question, in your own words
- **source** — the URL it came from
- **restriction** — the limit attached to it: a date, a season, a region, a
  version, a closure, an exception, a licence condition, a "but only if"

Leave `restriction` empty only when there genuinely is none. It is the field
that earns the whole step.

Send them together. Every tool call is a step in a chain, and a chain that grows
too long stops producing an answer at all — measured, on this agent: notes sent
one at a time pushed a turn to twelve calls, and it ended with no reply. Four
notes in one call cost one step. This is the same reason `web_search` takes
several queries and `web_read` several pages.

A page will often carry a general statement and its correction a sentence apart
— a season of opening, then a closure that overrides it — and the correction is
the more important half. Measured on this agent: it read exactly such a page,
answered correctly when asked about it directly, and still recommended the
closed place in its report. Nothing was misread. The qualifier simply did not
survive the distance between reading several pages and composing an answer.

The notes close that distance — but only if you look at them again. Call
**`notes_review` immediately before you write**, every time you took notes. It
hands back everything you recorded, restrictions included.

This is not a formality. Measured: an agent noted that one review named a
certain machine as its winner, then wrote that a different machine was that
review's winner. The note was right. The answer was built from memory of the
reading rather than from the note, twenty tool calls later, and by then the
reading had faded.

The notes are shown beside your answer, along with whether you re-read them. A
restriction that is in them and missing from what you wrote is visible to
whoever reads it.

## 3. Weigh what came back

This is the part a search engine cannot do, and the reason a person asked you
rather than a search box.

- What do **several independent sources** agree on? That is your backbone.
- What does **only one** say? Report it as such — not as fact, not as noise.
- What **contradicts**? Name both sides. Never split the difference.
- What is **old**? A number from three years ago is a number about three years
  ago, and in fast-moving subjects that makes it wrong rather than dated.
- What is **selling something**? A vendor's own page is a source about what the
  vendor claims.

Then decide whether you know enough. If a gap is now visible that was not
before, **search again** — with the terms the reading gave you, which are almost
always better than the ones you started with. That second round is where
research stops being a lookup.

Two rounds is usual. A third needs a reason you can name.

You have a **budget** for the turn — a number of searches and a number of pages
— and the tools tell you what is left with every answer. It is there to be
spent, not hoarded: reading nine pages in one call costs the same one round trip
as reading three. But when it is gone it is gone, and the honest end is to say
so in the report rather than to stop quietly. "Budget aufgebraucht" is one of the
three valid reasons to stop, alongside "answered" and "further rounds would only
repeat".

## 4. Check the load-bearing facts at the source — with `verify`

Searching wider is not the same act as checking. More rounds give you more
material and, with it, more variance: what lands on top depends on what the
engines happened to rank today, so the same question answered twice comes out
differently. Verification is what makes an answer reproducible — a figure
confirmed at its origin is the same figure next week.

Name the facts the **recommendation rests on** — usually a handful: a version, a
size, a price, a limit, a licence. For each of those, and only those:

**Go to the thing itself** with `web_read`. The project's own repository, its
model card, the vendor's own documentation, the official register, the listing
that carries the specification. Not an article about it, not a comparison of
others. Those are fine for finding candidates and useless for confirming
numbers.

**The check rides on the note.** When the page you are reading IS the source of
a figure, put `result` on that note and the figure is checked — no second call,
no separate act. Three results, all of them real: `confirmed` (the page says
it), `contradicted` (it says something else), `not_found` (it has not
got it, or would not load). A decisive figure that is *not* at its source is
often the most useful line in the whole report.

`verify` still exists as a tool of its own, for checks you make after the fact —
you went back to a page to settle something. It books into exactly the same
place. But the ordinary way is the note: a figure you just read is a figure you
can still place, and twenty calls later you are working from memory of it.

`verify` is checked against what the tools actually fetched. A source you did
not open this turn is refused, because a check that was only asserted is not a
check. If a page would not load at all — and manufacturers' pages increasingly
assemble themselves in a browser and hand a reader nothing — `not_found`
against that same address is the honest record, and it is accepted.

**Watch for the wrong edition.** Most confidently wrong figures come from a page
about the previous version, the other variant, the other region. If a name
carries a number, check that the page you are reading carries the same one.

**Name a contradiction rather than picking a side.** When two sources disagree
on something the decision hangs on, the primary source settles it; if it does
not exist or does not say, report that both claims exist and that it is
unresolved.

This step is bounded on purpose. Not every sentence gets verified — only what
the answer would be wrong without.

### The open points

When you call `notes_review`, it hands back an `open` list: notes whose own
restriction says the figure was never established — *not confirmed*, *not
found*, *unclear*. That list is computed from what you wrote, not from what you
remember. (The detection reads German as well, so a restriction that comes back
from a German page in its own words still counts.)

Two endings are allowed for each, and both are complete:

1. go to the source, and record the outcome with `verify`
2. say in the report, in plain words, that it stayed open

There is no third. Passing over an open point in silence is the failure this
step exists to prevent — and it is the one that was measured: an answer that
named its own gap in its notes, walked past it, and read as finished.

## 5. Report

Built from what `notes_review` handed back, never from memory of the reading. The answer first, in
one or two sentences. Then the evidence, each claim beside the source it came
from — and where a note carried a restriction, the restriction travels with the
claim. A recommendation whose limitation was dropped is not a shortened
recommendation, it is a wrong one. Then, last and always present:

- which load-bearing facts you **checked at the source**, and what came back —
  confirmed, contradicted, or not findable
- what stayed **uncertain**, and why
- what you **assumed** at the start, so it can be corrected
- **why you stopped** — answered, exhausted, or out of budget

A research report without a section on its own limits is a report that has
stopped distinguishing what it found from what it hopes.

## The failure to guard against

Not a wrong answer — a **complete-looking** one. You know a lot without
searching, and that knowledge will offer itself to fill any gap, in the right
tone, in the right shape, indistinguishable from something you read. Every claim
either has a source beside it or is marked as unverified. There is no third
option, and „das ist allgemein bekannt" is not one.

The same goes for a failed search. The tools distinguish *nothing found* from
*could not search*; you must too. Reporting a broken search engine as „dazu gibt
es nichts" is the most expensive sentence you can write, because nobody checks
an answer that sounds finished.
