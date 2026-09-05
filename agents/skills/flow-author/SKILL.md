---
name: flow-author
description: Use this whenever someone wants a flow (a pipeline, a recipe, an automation) built or changed - "I want a clip from my pictures every week", "can the machine make a post from a text", "build me something that turns X into Y" - or describes a result they want made and no saved flow does it yet. It is the method for turning that wish into a saved flow in the library: ask what comes out and what goes in, choose the steps from the vocabulary rather than from memory, put a pause in front of anything that costs, check the draft with the tool, show it in words, and save only when they say yes. It never runs a flow.
---

# Authoring a flow

A flow is a fixed recipe: steps, each a verb this workshop already knows,
wired so that one step's result is the next step's input. You do not carry out
any step and you do not start the flow. You find out what the person wants
made, compose the recipe from the vocabulary, have the machine check it, show
it, and save it when they agree. Someone else runs it.

Four tools, and only these:

| Tool | When |
|---|---|
| `flow_ops` | before proposing any step; again with `after` to see what can follow |
| `flow_check` | on every draft, and after every correction |
| `flow_save` | once, after the person said yes to what you showed |
| `flows_list` | when they mention an existing flow, or to avoid a name that is taken |

## Pass one — understand the job

Read `QUESTIONS.md` beside this file and work through it in order, **one
question per turn**, in your own words. React to each answer before moving
on. Skip anything an earlier answer already covered.

The first two questions - what should exist at the end, and what the person
brings to start from - get **no offers**: they are the whole job, and a person
handed three suggestions picks somebody else's job. Every question after them
narrows, and there you offer two or three concrete shapes the answer could
take, derived from what they said, plus the honest empty one ("nothing", "I
don't know", "not yet").

**A wish is not a flow yet.** "Something for social media" names no artefact.
Ask until you can say in one sentence: *from THIS, the machine makes THAT.*
If you cannot say it, you cannot build it; keep asking, smaller.

## Pass two — compose

**Read the vocabulary; do not remember it.** Call `flow_ops` before the first
step. Op names and parameter names come from that answer and from nowhere
else - a name from memory is a name that may not exist, and the check will
refuse it, or worse, a similar one will run.

Build the chain from what comes in to what goes out, one step at a time. After
placing a step, call `flow_ops` with `after` set to it: the answer is the list
of steps that can take its output, and the choice is made among those. Types
decide: a picture cannot go into a step that reads text, and the tool will not
show you one.

**A pause before every cost.** Look at each step's `cost` and `effect` in the
answer. Before a step that spends money, minutes on the GPU, or sends anything
out of the house, put a `review` (the person sees the last result and decides)
or a `gate` (the person decides without seeing). Ask the person where they
want to look; do not decide that for them, and do not leave it out because
they did not mention it - they do not know the steps cost until you say so.

**What varies goes into `args`.** A subject, a text, a number that changes
from run to run is `{"arg": "<name>"}`, with a `default` if the person gave a
typical value. What is fixed is written in. Ask which is which if it is not
obvious.

**Check, fix, check.** Call `flow_check` with the whole draft. Read every
problem it lists, fix all of them, call it again. Not one problem per round -
all of them. If after three rounds the same problem stands, stop and tell the
person what the machine refuses and why; do not save around it.

The spec's shape is in `FORMAT.md` beside this file. Read it when you write
the first draft, not from memory.

## Pass three — show, then save

**Show the flow in words, never as JSON.** A numbered list, one line per step,
in the person's language: what goes in, what each step makes, where it pauses
for them, where the result goes. Then the one sentence: *from THIS, the
machine makes THAT.* Name what varies per run. Then ask whether to save it,
and under which name (propose one: lowercase, digits, dashes).

**Save only on a yes.** `flow_save` once, with the name they agreed to. If the
name is taken, say so and ask - never overwrite on your own. After saving,
say the name and that nothing has been started; they run it themselves, or ask
for it to be run.

**Never run it.** You have no tool to start a flow from here, and that is
deliberate: an author who also runs is an author who runs to see whether it
works, on the person's GPU minutes and money. If they want it run, that is a
different conversation with a different agent.

## When the vocabulary cannot do it

If no runnable op makes what is wanted - a format nobody renders, a service
nobody connected - say so plainly: which part of the job has no step, in one
sentence. Do not substitute something similar and call it done. A flow that
makes the wrong thing costs a run to find out; a sentence costs nothing.

## Never

- name an op or a parameter you did not read in `flow_ops` this conversation
- save a flow `flow_check` has not passed
- save before the person said yes to the words you showed
- overwrite without being told to
- report a flow as saved unless `flow_save` answered ok
- describe steps you did not put in, or leave out a pause you did
