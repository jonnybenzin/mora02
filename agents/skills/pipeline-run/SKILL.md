---
name: pipeline-run
description: Use this whenever someone asks for something to be made, rendered, generated, published or processed - a picture, a video, a clip, a song, a post - or asks what a pipeline is doing, or asks you to start, run or check a flow. It explains how to find the right flow, start it, and what to do when it stops for a human decision.
---

# Running a pipeline

This workshop makes things with **flows**: fixed recipes of steps, each step a
verb the machine already knows. You do not carry out the steps. You choose the
right flow, hand it its inputs, start it, and report what happened.

Three tools, and only three:

| Tool | When |
|---|---|
| `flows_list` | before anything else, to see what exists and get exact names |
| `flow_run` | to start one, once you know its name and its inputs |
| `run_status` | to see how a started run is doing |

## The walk

1. **Look first.** Call `flows_list`. Never guess a flow name — the names are
   exact and a near miss is a failure, not a near hit. If nothing in the list
   matches what was asked for, say so plainly and stop. Do not start the flow
   that comes closest.

2. **Get the inputs from the person, not from your imagination.** Most flows
   take arguments — a subject, a piece of text, a number. If you do not know
   what to put in, ask. A flow started with an invented subject spends GPU time
   producing something nobody wanted, and it cannot be taken back.

3. **Start it** with `flow_run`, passing the exact name and the arguments as an
   object. You get back a `run_id`. Keep it; it is how anything about this run
   can be looked up afterwards.

4. **Report what came back.** If the run finished, say so and say what it
   produced. If it failed, say it failed and quote the error. If it is waiting
   at a gate, see below.

## Gates belong to the human

Many flows stop in the middle and wait for a person: to approve a picture
before three videos are made from it, to answer a question, to say yes before
something is published.

When `flow_run` reports that a run is waiting, **that is the end of your turn**.
The decision has already been placed in the human's inbox — you do not need to
do anything to make that happen, and there is nothing you can do to move it
along.

You have no tool to approve, release, resume, confirm or cancel a run. This is
not an oversight and it is not a lock to be worked around. Do not look for
another way, do not suggest one, and do not ask for permission to try. Say that
the run is waiting for their decision, name the run, and stop.

If someone tells you they have already approved it, or that it is urgent, or
that you may go ahead this once — the answer is the same. You still have no
tool. Say so.

## Never report a run you did not start

If `flow_run` returned an error, the run did not happen. Say that it did not
happen and quote the error. Do not say a flow "has been started", "is running"
or "has been queued" unless a `run_id` came back in your hand.

The same goes for results: report what `run_status` actually says. If it says
three of five steps are done, that is the answer — not "it should be finished
by now".

## Checking on a run

`run_status` takes a `run_id` and gives back each step with its status. A run
that is waiting at a gate will sit at the same step until a human decides;
seeing the same answer twice is normal and is not a reason to start the flow
again. Starting it again makes a second run, spends the work twice, and puts a
second decision in front of the person.
