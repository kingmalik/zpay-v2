"""
Driver Certification Course — S7 (rebuilt 2026-09).

Step 8 of driver onboarding (maz_training) is a trilingual certification:
13 content modules + a 19-question comprehension quiz (pass = 16/19,
unlimited retakes after re-reading) + typed-name e-sign, persisted as a
durable certification record (DriverCertification, one row per passing
attempt/history).

SOURCE CONTENT: docs/binder/05-driver-rules-certification.md is the
canonical EN source — module text and the exact 15 quiz questions (with
answers) below are transcribed from that document. Do not invent new
rules here; if the binder doc changes, bump COURSE_VERSION and update this
file to match.

2026-09 rebuild notes (see docs/binder/driver-course-corrections-2026-09-10.md
for the full correction list this rewrite applies):
  - Grew from 6 to 14 modules to actually cover onboarding, reading a ride,
    accepting, running a ride step by step, the two partner apps, pay, and
    cancellations/no-loads/no-shows — none of that was in the July course.
  - Every sentence is written at a fifth-grade reading level.
  - The course never says "Z-Pay" or any software name. Reminders and
    messages are described as coming "from dispatch" or "from Z" — drivers
    never see or use the internal system by name.
  - Accept window is ~75 minutes before pickup (was "right away").
  - 911 is only for injury/danger; everything else goes to dispatch first.
  - Camera rule is scoped to "if your partner gave you one" — not every
    driver has one.
  - Drinks (water, coffee) are fine in the car; eating is not. The real
    rule taught is "nothing that takes your eyes or hands off driving."
  - Pay lag is stated exactly: rides driven Monday-Friday are paid on the
    Friday two weeks later; how partners pay Maz is out of scope for
    drivers. Deposit day is Friday (was wrongly "about Thursday").
  - No-load wait is 5-10 minutes (district sets it) at full pay; a late
    cancellation 1-2 hours before the ride is also full pay; a driver
    no-show is zero pay plus a contract conversation.
  - No guardian/parent contact, ever — drivers talk to Maz dispatch and
    the partner's dispatch only. The old "dispatch calls the parent" line
    is gone.
  - The scorecard module teaches six raw numbers (acceptance, on-time
    start, on-time arrival, on-time completion, responsiveness,
    reliability) — no Gold/Silver/Bronze/Probation tiers.
  - The dispatch phone number is a placeholder (the dedicated line isn't
    built yet) — see DISPATCH_PHONE_DISPLAY below, interpolated in exactly
    one place in the course text.
  - Quiz dropped the old "camera not working" question (camera is no
    longer a blanket rule) and added 15 questions total covering: accept
    window, the EverDriven At Pickup tap, pickup/dropoff zones, no-load
    wait+pay, late-cancel pay, pay day, the under-$100 carry rule, drinks
    vs. eating, 911 vs. dispatch, camera-if-given, vest/placard, reading a
    ride name (IB/OB, ride number = same student all year), the wheelchair
    swap rule, calling in sick, and expired documents.

2026-09-10 depth pass notes (same COURSE_VERSION, same 14 modules/order,
same schema — content only): Malik reviewed the 2026-09 rebuild and called
it an outline, not training (3-8 one-liners per module). Every module was
rewritten to 8-16 blocks, each block one idea in one or two short
sentences, still fifth-grade reading level, still no Z-Pay/software name,
still no explanation of how partners pay Maz, still no parent/school
contact. `lead` is now used as a short bold step/example label ("Step 1",
"Example", "Why it matters") throughout, not just for a handful of blocks.
The quiz grew from 15 to 20 questions (pass stays 16/20 — same 0.8 ratio,
PASS_THRESHOLD_RATIO unchanged) with 5 new questions covering: the 1099
contractor / no-taxes-taken-out fact, the no-other-passengers rule, the
seat belt / car seat rule, answering a partner dispatcher's direct call,
and what to do when the app won't let you start a ride. COURSE_VERSION was
deliberately NOT bumped here — bumping forces fleet-wide recertification,
which is a call for Malik/Z, not a default side effect of a content-depth
pass. Bump it in a follow-up commit once that's decided.

Translations: this pass ships English only. The 'am' and 'ar' keys below
are intentionally set equal to the English string for now — a follow-up
translation pass replaces them (Amharic needs a native-speaker check per
the binder doc's translation flow note; Arabic needs a second full-speaker
QA pass). The frontend renders whatever is in these dicts, so the course
still works end-to-end in this state, just English-only until that pass
lands.

2026-09-10 Round 4 notes (same COURSE_VERSION, content only): the
"Reading your ride" module is gone — IB/OB, ride numbers, and (W) day
variants were internal dispatch vocabulary, not driver knowledge. Its one
useful block ("read the notes before you accept") moved into "Accepting a
ride". All wheelchair content was removed — Z assigns wheelchair rides
only to approved drivers, so drivers don't need the rule. The pay-delay
explanation in "How you get paid" was expanded from one block into a
dated, walked-through sequence (why the delay exists, the exact rule, a
worked example, the first-three-Fridays pattern for a new driver, the
stub arriving first, and the under-$100 carry rule). Module count dropped
14 -> 13; quiz dropped 20 -> 19 (one ride-name question and one wheelchair
question removed, one pay-delay question added). Pass threshold is still
0.8 of quiz_total, i.e. 16 of 19.

Recertification: is_certified()/needs_recert() key off COURSE_VERSION —
any driver whose latest certification row doesn't match the current
COURSE_VERSION is treated as not (or no longer) certified. Bump
COURSE_VERSION whenever module or quiz content changes in a way that
matters (a rule changes, a question changes) — this is a full recert
trigger for the whole fleet, so don't bump it for typos.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

# Bump on any content change that should force fleet-wide recertification.
COURSE_VERSION = "2026-09"

# Quiz pass threshold — 16 of 19 (binder doc §Quiz). Expressed as a ratio so
# a future change to quiz_total still resolves to "16 of 19"-equivalent.
PASS_THRESHOLD_RATIO = 0.8

LANGS = ("en", "am", "ar")

# The dedicated dispatch line isn't built yet (binder corrections doc,
# item 14 / round 2). Course ships with this placeholder number until a
# real line exists — interpolated in exactly one place in the course text
# (Module 1, "Who we are, who you talk to").
DISPATCH_PHONE_DISPLAY = os.environ.get("DISPATCH_PHONE_DISPLAY", "(206) 832-5689")


def pass_threshold(quiz_total: int) -> int:
    """Minimum quiz_score required to pass a quiz of quiz_total questions."""
    return math.ceil(quiz_total * PASS_THRESHOLD_RATIO)


def quiz_passes(quiz_score: int, quiz_total: int) -> bool:
    if quiz_total <= 0:
        return False
    return quiz_score >= pass_threshold(quiz_total)


# ---------------------------------------------------------------------------
# Course content — 13 modules
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModuleBlock:
    """One paragraph/bullet inside a module. `lead` is an optional bold
    lead-in phrase (e.g. "Accept on time.") rendered ahead of `text`."""
    lead: Optional[dict]  # {"en": str, "am": str, "ar": str} or None
    text: dict            # {"en": str, "am": str, "ar": str}


@dataclass(frozen=True)
class CourseModule:
    key: str
    title: dict
    intro: Optional[dict]   # optional lead sentence before the block list
    blocks: tuple[ModuleBlock, ...]


def _tri(text_en: str) -> dict:
    """English-only pass — am/ar intentionally mirror en. See module
    docstring. A follow-up translation pass replaces am/ar in place."""
    return {"en": text_en, "am": text_en, "ar": text_en}


def _block(text_en: str, lead_en: Optional[str] = None) -> ModuleBlock:
    return ModuleBlock(lead=_tri(lead_en) if lead_en else None, text=_tri(text_en))


COURSE_MODULES: tuple[CourseModule, ...] = (
    CourseModule(
        key="m1",
        title=_tri("Who we are, who you talk to"),
        intro=None,
        blocks=(
            _block(
                "Maz Services drives kids who need extra help to and from school.",
                lead_en="Who we drive.",
            ),
            _block(
                "We work with two partner companies: FirstAlt and EverDriven. They send "
                "us the rides.",
                lead_en="Our partners.",
            ),
            _block(
                "You only talk to two people about a ride: Maz dispatch, and the "
                "partner's dispatch. No one else.",
                lead_en="Two people you talk to.",
            ),
            _block("You never call a parent. You never call the school. That is not your job."),
            _block(
                "FirstAlt or EverDriven dispatch might call you directly about a ride. "
                "Answer the call and do what they say.",
                lead_en="Partner dispatch may call you.",
            ),
            _block(
                "After you talk to the partner's dispatch, call or message Maz dispatch "
                "too. Keep us in the loop.",
                lead_en="Then tell Maz.",
            ),
            _block(f"Call dispatch at {DISPATCH_PHONE_DISPLAY}.", lead_en="Need dispatch?"),
            _block("Questions about your pay or your rate go to Z. Not to dispatch.", lead_en="Pay questions."),
            _block(
                "Clear phone lines keep every ride safe. Everyone knows exactly who to call.",
                lead_en="Why this matters.",
            ),
        ),
    ),
    CourseModule(
        key="m2",
        title=_tri("Getting onboarded"),
        intro=_tri(
            "You already did most of this to get here. This is a quick map of the "
            "whole path, so you understand each piece.",
        ),
        blocks=(
            _block("You get an invite link from FirstAlt to start your file.", lead_en="FirstAlt: step 1."),
            _block(
                "FirstAlt runs your background check. Have your last 7 years of "
                "addresses and your last 3 years of work ready — they ask for both.",
                lead_en="FirstAlt: step 2.",
            ),
            _block(
                "You sign a drug test consent form. Then Priority Solutions calls to "
                "book your drug test at Concentra, before your first ride.",
                lead_en="FirstAlt: step 3.",
            ),
            _block("You take the FirstAlt online class.", lead_en="FirstAlt: step 4."),
            _block(
                "You upload your license, registration, insurance, and photos of your "
                "vehicle. Every document needs its expiry date on it.",
                lead_en="FirstAlt: step 5.",
            ),
            _block(
                "You sign the Acumen contract, take this course, then sign the Maz "
                "contract.",
                lead_en="FirstAlt: step 6.",
            ),
            _block("EverDriven runs a different path. Here it is, step by step.", lead_en="EverDriven track."),
            _block(
                "You register in the Contractor Compliance app and upload your license, "
                "registration, and insurance.",
                lead_en="EverDriven: step 1.",
            ),
            _block(
                "You get fingerprinted for a background check and take an in-person "
                "drug and alcohol test.",
                lead_en="EverDriven: step 2.",
            ),
            _block(
                "Your vehicle passes a 50-point inspection, and a mechanic signs off on it.",
                lead_en="EverDriven: step 3.",
            ),
            _block(
                "You take the Hallo English test — about 10 minutes, 5 speaking questions.",
                lead_en="EverDriven: step 4.",
            ),
            _block(
                "You take the SafeRide online safety course — about 4.5 hours.",
                lead_en="EverDriven: step 5.",
            ),
            _block(
                "You set up your banking, install the EverDriven driver app, then pick "
                "up your vest and window sticker.",
                lead_en="EverDriven: step 6.",
            ),
            _block(
                "You are paid as a 1099 contractor, not an employee. No taxes are taken "
                "out of your pay.",
                lead_en="You are your own business.",
            ),
            _block(
                "You owe your own taxes on what you earn. Set some of every paycheck "
                "aside for tax time.",
                lead_en="What that means.",
            ),
            _block(
                "You fill out a form called a W-9. Pick \"Individual/sole proprietor\" "
                "unless you have an LLC. After the year ends, you get a 1099 form "
                "showing what you earned.",
                lead_en="The W-9 form.",
            ),
        ),
    ),
    CourseModule(
        key="m3",
        title=_tri("Your vehicle and gear"),
        intro=None,
        blocks=(
            _block(
                "Keep your registration, insurance, and inspection current. If one "
                "expires, you cannot drive until it is fixed. No exceptions.",
                lead_en="Registration, insurance, inspection.",
            ),
            _block(
                "An expired document can end a ride before it starts, and it can cost "
                "you routes.",
                lead_en="Why it matters.",
            ),
            _block("Wear your vest. Put your placard in the window. Every ride, every day.", lead_en="Vest and placard."),
            _block(
                "Some drivers have a partner-issued camera in their van. If you were "
                "given one, keep it on for every ride.",
                lead_en="Camera, if you have one.",
            ),
            _block("Not every driver has a camera. If you don't have one, you don't need one.", lead_en="No camera? That's fine."),
            _block(
                "A clean car is part of the job. Trash, smells, and clutter are not okay "
                "with a child in the car.",
                lead_en="Keep the car clean.",
            ),
            _block(
                "Never smoke or vape in the car — not before a ride, not between rides. "
                "No smoke smell, ever.",
                lead_en="No smoking, no vaping.",
            ),
            _block(
                "No other passengers, ever. Not your kids, not your friends, not another "
                "driver. Only the student on your route.",
                lead_en="Only the assigned rider.",
            ),
            _block(
                "Every rider is checked in and tracked. An extra person in the car is "
                "not allowed and is not safe.",
                lead_en="Why.",
            ),
            _block(
                "Your spouse needs a ride and it's right on your way. Still no — the car "
                "is for the assigned student only, every time.",
                lead_en="Example.",
            ),
        ),
    ),
    CourseModule(
        key="m4",
        title=_tri("Accepting a ride"),
        intro=None,
        blocks=(
            _block(
                "Before you accept, read the ride notes. They tell you about a booster "
                "seat, an allergy, or how the child likes things done.",
                lead_en="Read the notes.",
            ),
            _block("The app lets you accept a ride about 75 minutes before pickup.", lead_en="The window."),
            _block("Accept the moment the ride opens. Don't wait.", lead_en="Accept fast."),
            _block(
                "At 75 minutes before pickup, the ride shows up as ready to accept.",
                lead_en="Step 1.",
            ),
            _block(
                "If you haven't accepted, you get a text reminder around this time.",
                lead_en="Still waiting — 75 minute mark.",
            ),
            _block(
                "At 45 minutes before pickup, dispatch calls you directly.",
                lead_en="Still waiting — 45 minute mark.",
            ),
            _block(
                "At 30 minutes before pickup, Z is alerted that the ride is still open.",
                lead_en="Still waiting — 30 minute mark.",
            ),
            _block(
                "Every call you get because you didn't accept is a mark against you. Too "
                "many, and you can lose routes.",
                lead_en="Why it matters.",
            ),
            _block("Partners can see how fast you accept. Fast acceptance builds trust.", lead_en="Partners are watching."),
            _block(
                "A ride opens at 7:00 for an 8:15 pickup. Accept it right then — don't "
                "wait until 7:45.",
                lead_en="Example.",
            ),
        ),
    ),
    CourseModule(
        key="m5",
        title=_tri("Running the ride, step by step"),
        intro=None,
        blocks=(
            _block("Tap Start in the app the moment you leave for pickup.", lead_en="Step 1: Start."),
            _block(
                "Follow the route the app gives you. Read the notes twice if it's your "
                "first time on this route.",
                lead_en="Step 2: drive the route.",
            ),
            _block("Get to the pickup spot on time — early is on time.", lead_en="Step 3: arrive."),
            _block(
                "When you arrive, tap At Pickup. This tells dispatch you made it. A lot "
                "of drivers skip this — don't be one of them.",
                lead_en="EverDriven: tap At Pickup.",
            ),
            _block(
                "For afternoon pickups, wait at the school pickup spot. Staff bring the "
                "student out to you.",
                lead_en="PM pickup at school.",
            ),
            _block(
                "If the student doesn't come out, call dispatch. Never go inside the "
                "school. Never call the school yourself.",
                lead_en="If the student doesn't come out.",
            ),
            _block(
                "Wait 5 to 10 minutes — the school district sets the exact time — then "
                "call dispatch.",
                lead_en="No-load steps.",
            ),
            _block(
                "Dispatch tells you to mark it a no-load in the app. You still get full pay.",
                lead_en="No-load: what dispatch tells you.",
            ),
            _block(
                "Call dispatch before you move the car. Don't guess.",
                lead_en="Wrong address or notes don't match.",
            ),
            _block(
                "Only drop the student at the exact stop you were given. Never a "
                "different spot, even if asked.",
                lead_en="Step 4: drop-off.",
            ),
            _block(
                "Tap End in the app while you are still at the drop-off spot. Then you "
                "can close the app.",
                lead_en="Step 5: End.",
            ),
            _block(
                "Tapping Start or End from the wrong place can look like a fake ride, "
                "and dispatch may have to take that pay back.",
                lead_en="Why the exact spot matters.",
            ),
            _block(
                "If the partner's dispatch calls you during a ride, answer and follow "
                "their directions. Then tell Maz dispatch what happened.",
                lead_en="Partner dispatch may call mid-ride.",
            ),
        ),
    ),
    CourseModule(
        key="m6",
        title=_tri("The two apps"),
        intro=None,
        blocks=(
            _block(
                "FirstAlt app screens, in order: Assign, Accept, En Route, Onboard, Complete.",
                lead_en="FirstAlt screens.",
            ),
            _block(
                "Assign is your ride waiting. Accept confirms it's yours. En Route means "
                "you're driving there. Onboard means the student is in the car. "
                "Complete means the ride is done.",
                lead_en="What each FirstAlt screen means.",
            ),
            _block(
                "EverDriven app screens, in order: Scheduled, Accepted, Active, At "
                "Pickup, Completed.",
                lead_en="EverDriven screens.",
            ),
            _block(
                "Scheduled is the ride waiting. Accepted confirms it's yours. Active "
                "means you're driving. At Pickup means you arrived. Completed means the "
                "ride is done.",
                lead_en="What each EverDriven screen means.",
            ),
            _block(
                "The At Pickup tap is easy to miss. Tap it every time you arrive — it's "
                "your proof that you showed up.",
                lead_en="The tap most drivers miss.",
            ),
            _block("Keep the app installed, logged in, and notifications turned on.", lead_en="Keep the app ready."),
            _block(
                "Keep location and GPS turned on, your phone charged, and mounted where "
                "you can see it while driving.",
                lead_en="Keep your phone ready.",
            ),
            _block("Take a screenshot of the screen.", lead_en="If the app won't start a ride."),
            _block("Call dispatch before you drive. Never drive a ride the app can't track.", lead_en="Then."),
            _block(
                "Always tap Start and End while you're inside the pickup or drop-off "
                "zone, not from your driveway or down the street.",
                lead_en="Start and end in the zone.",
            ),
        ),
    ),
    CourseModule(
        key="m7",
        title=_tri("The six driving rules"),
        intro=None,
        blocks=(
            _block(
                "When the app offers your ride, accept it as soon as you can. See the "
                "Accepting a ride module for the exact window.",
                lead_en="1. Accept on time.",
            ),
            _block("Being early is on time. Being right on time is cutting it close.", lead_en="2. Arrive on time."),
            _block(
                "No stops — not for gas, not for coffee, not for errands. Fill your tank "
                "before your route starts.",
                lead_en="3. Straight there, straight home.",
            ),
            _block(
                "Water and coffee are fine. No eating. The real rule: nothing that takes "
                "your eyes or your hands off driving.",
                lead_en="4. No eating while you drive.",
            ),
            _block(
                "Never hold your phone while driving. Mount it, and only touch it when "
                "you're stopped.",
                lead_en="No phone in hand.",
            ),
            _block(
                "Follow the route the app gives you. If the road is blocked, call "
                "dispatch — don't decide on your own.",
                lead_en="5. No detours.",
            ),
            _block("Every ride is tracked. Speeding shows up.", lead_en="6. Never speed."),
            _block("These six rules protect the kids in your car and protect your routes.", lead_en="Why these six."),
            _block(
                "You're running 5 minutes late. Don't speed to make it up — call "
                "dispatch instead.",
                lead_en="Example.",
            ),
            _block(
                "You need coffee before your shift. Get it before you accept the ride, "
                "not on the way.",
                lead_en="Example.",
            ),
        ),
    ),
    CourseModule(
        key="m8",
        title=_tri("The children"),
        intro=None,
        blocks=(
            _block(
                "Greet the child by name. Use the same seat every day if the child "
                "prefers it — routine is comfort.",
                lead_en="Greet and settle.",
            ),
            _block("Every child wears a seat belt, every ride, no exceptions.", lead_en="Seat belts, every time."),
            _block(
                "If the notes say a child needs a car seat or booster, use it every "
                "time. Never skip it.",
                lead_en="Car seats and boosters.",
            ),
            _block(
                "Crying, shouting, won't stay seated — pull over somewhere safe and "
                "call dispatch.",
                lead_en="If a child has a hard moment.",
            ),
            _block("Never discipline. Never grab. Never argue. Dispatch handles it from there.", lead_en="What you never do."),
            _block(
                "Never leave a child alone in the vehicle, for any reason, for any "
                "amount of time.",
                lead_en="Never leave a child alone.",
            ),
            _block(
                "Never drop a child anywhere but the exact stop you were given, even if "
                "someone asks you to.",
                lead_en="Exact stop only.",
            ),
            _block(
                "What happens in the car stays private. No photos of children. No posts "
                "about your riders, ever.",
                lead_en="Privacy.",
            ),
            _block(
                "These are kids, and their families trust us to keep their information safe.",
                lead_en="Why privacy matters.",
            ),
        ),
    ),
    CourseModule(
        key="m9",
        title=_tri("When something goes wrong"),
        intro=None,
        blocks=(
            _block("Call 911 first. Then call dispatch.", lead_en="Someone is hurt or in danger."),
            _block("Call dispatch first. Not 911.", lead_en="Anything else."),
            _block("Pull over somewhere safe. Call dispatch.", lead_en="Child gets sick in the car."),
            _block("Pull over, call dispatch, and stay calm. Never grab.", lead_en="Child unbuckles or hits."),
            _block(
                "Pull over, stay with the child, and call dispatch. Someone will come "
                "to you.",
                lead_en="Breakdown with a child in the car.",
            ),
            _block("Check that everyone is okay. Call 911 if anyone is hurt.", lead_en="Accident: check everyone first."),
            _block(
                "Call dispatch right after 911, or right away if no one is hurt.",
                lead_en="Accident: then call dispatch.",
            ),
            _block("Take photos of both cars and the scene.", lead_en="Accident: take photos."),
            _block(
                "Get the other driver's name, license plate, and insurance information.",
                lead_en="Accident: get the other driver's info.",
            ),
            _block("Write down what happened within 24 hours. Just the facts.", lead_en="Accident: write it down."),
            _block(
                "Never say whose fault the accident was. That's not your call to make.",
                lead_en="Accident: never say whose fault.",
            ),
            _block("Call dispatch the second you know — even at 5am.", lead_en="Sick or can't drive."),
            _block("Say so before the next ride is at risk.", lead_en="Running late on one ride of a loop."),
            _block("Dispatch will tell you. Never drive to a closed school.", lead_en="Snow day or a closure."),
            _block("Call dispatch before pickup time is due, not after.", lead_en="Late in general."),
        ),
    ),
    CourseModule(
        key="m10",
        title=_tri("How you get paid"),
        intro=None,
        blocks=(
            _block(
                "Pay is set per ride and per route by Z. It's not per hour, and it's "
                "not per mile.",
                lead_en="Pay is per ride.",
            ),
            _block("There's no pay for driving between rides.", lead_en="No pay between rides."),
            _block("You get paid weekly.", lead_en="Weekly pay."),
            _block(
                "You do not get paid the same week you drive. Every ride is checked and "
                "counted first. That takes time.",
                lead_en="There is a delay.",
            ),
            _block(
                "Rides you drive Monday to Friday are paid on the Friday two weeks later.",
                lead_en="The rule.",
            ),
            _block(
                "You drive Monday, September 14 to Friday, September 18. That money "
                "lands on Friday, October 2.",
                lead_en="Example.",
            ),
            _block(
                "New driver? Your first Friday: nothing yet. Second Friday: nothing "
                "yet. Third Friday: your first pay. After that, every Friday.",
                lead_en="Your first three Fridays.",
            ),
            _block(
                "A few days before the money lands, you get a pay stub by email. It "
                "shows the week, your rides, and your total.",
                lead_en="Your stub comes first.",
            ),
            _block(
                "If you earn under $100 in a week, it is not lost. It is added to the "
                "next week.",
                lead_en="Under $100.",
            ),
            _block("Pay comes by direct deposit.", lead_en="Direct deposit."),
            _block(
                "Held back means Z is holding money for a reason she'll explain — for "
                "example, a ride that got paid twice by mistake gets taken back the "
                "next week.",
                lead_en="What \"held back\" means.",
            ),
            _block(
                "In May, a driver was paid twice for the same ride. The extra pay was "
                "taken back the next cycle, and the stub showed it as held back.",
                lead_en="Example.",
            ),
            _block(
                "Reply to the stub email or message Z. Give her the ride date and the "
                "route name.",
                lead_en="If you spot a mistake.",
            ),
            _block("Mistakes get fixed the next pay cycle.", lead_en="Mistakes get fixed."),
            _block("Pay and rate questions go to Z. Not to dispatch.", lead_en="Who to ask."),
        ),
    ),
    CourseModule(
        key="m11",
        title=_tri("Cancellations, no-shows, no-loads"),
        intro=None,
        blocks=(
            _block("Ride cancelled 1 to 2 hours before it starts: you still get full pay.", lead_en="Late cancel."),
            _block(
                "Student not there? Wait 5 to 10 minutes — the school district sets the "
                "exact time.",
                lead_en="No-load wait.",
            ),
            _block("Call dispatch. Dispatch tells you to mark it a no-load in the app.", lead_en="No-load steps."),
            _block("You still get full pay for a no-load.", lead_en="No-load pay."),
            _block("You don't show up for a ride: no pay, and a talk about your contract.", lead_en="Driver no-show."),
            _block(
                "If the ride is cancelled the night before, nothing is owed to you — "
                "and you'll be told.",
                lead_en="Cancel the night before.",
            ),
            _block(
                "Your ride is at 7:30am. At 7:15, the partner cancels it. You still get "
                "full pay.",
                lead_en="Example.",
            ),
            _block(
                "You wait 8 minutes and no student comes out. You call dispatch, they "
                "tell you to mark it a no-load. Full pay.",
                lead_en="Example.",
            ),
        ),
    ),
    CourseModule(
        key="m12",
        title=_tri("Your scorecard"),
        intro=None,
        blocks=(
            _block(
                "Every week you get six numbers: acceptance, on-time start, on-time "
                "arrival, on-time completion, responsiveness, reliability.",
                lead_en="Six numbers.",
            ),
            _block("How fast and how often you accept rides.", lead_en="Acceptance."),
            _block(
                "Whether you started, arrived, and finished each ride on time.",
                lead_en="On-time start, arrival, completion.",
            ),
            _block("How fast you answer when dispatch calls or messages you.", lead_en="Responsiveness."),
            _block("Whether dispatch can count on you, ride after ride.", lead_en="Reliability."),
            _block("Drivers dispatch never has to chase get the most routes.", lead_en="Why it matters."),
            _block("Low numbers mean fewer routes, then a conversation.", lead_en="Low numbers."),
            _block("Partners can also remove a driver from their routes.", lead_en="Partners see it too."),
            _block("There are no ranks or labels. Just your six numbers.", lead_en="No ranks."),
        ),
    ),
    CourseModule(
        key="m13",
        title=_tri("Staying current"),
        intro=None,
        blocks=(
            _block(
                "Your registration, insurance, inspection, drug test, and background "
                "check all expire.",
                lead_en="What expires.",
            ),
            _block("Reminders come from dispatch, or from Z.", lead_en="Reminders."),
            _block("Renew the week you're told. Not the last day.", lead_en="Renew on time."),
            _block("Expired means no driving until it's fixed. No exceptions.", lead_en="If something expires."),
            _block("Send the new document to Z the same day you get it.", lead_en="Send it in."),
            _block(
                "An expired document can put a ride, and your routes, on hold.",
                lead_en="Why it's strict.",
            ),
            _block(
                "Your insurance renews on the 1st. If you're told to renew it that "
                "week, don't wait until the 28th.",
                lead_en="Example.",
            ),
            _block("Check your dates now so nothing catches you by surprise.", lead_en="Plan ahead."),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Quiz — 19 questions, single correct answer each (binder doc §Quiz)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuizQuestion:
    question: dict
    options: tuple  # tuple of dicts {"en":..., "am":..., "ar":...}
    correct: int


def _opt(en: str) -> dict:
    """English-only pass — see _tri() note above."""
    return _tri(en)


QUIZ_QUESTIONS: tuple[QuizQuestion, ...] = (
    QuizQuestion(
        question=_opt("The app opens a ride for you to accept. About how long before pickup does that happen?"),
        options=(
            _opt("About 75 minutes before"),
            _opt("Right away, no wait"),
            _opt("The night before"),
            _opt("Only after dispatch calls"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("In the EverDriven app, what does tapping At Pickup do?"),
        options=(
            _opt("Tells dispatch you made it to the pickup spot"),
            _opt("Starts your break"),
            _opt("Cancels the ride"),
            _opt("Turns on the camera"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("Why do you tap Start and End while you are inside the pickup and drop-off zones?"),
        options=(
            _opt("It's proof the ride happened — it's how you get paid"),
            _opt("It saves the app's battery"),
            _opt("It's just a formality"),
            _opt("It turns off notifications"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("The student is not outside. How long do you wait before you call dispatch and mark it a no-load, and what pay do you get?"),
        options=(
            _opt("5 to 10 minutes, then call dispatch — full pay"),
            _opt("1 minute, then leave — no pay"),
            _opt("30 minutes, then leave — half pay"),
            _opt("You never wait, drive off right away"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("The ride is cancelled 1 to 2 hours before it starts. What pay do you get?"),
        options=(
            _opt("Full pay"),
            _opt("No pay"),
            _opt("Half pay"),
            _opt("Pay only if you already left home"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("Rides you drive Monday to Friday are paid on..."),
        options=(
            _opt("The Friday two weeks later"),
            _opt("The next Monday"),
            _opt("The same Friday"),
            _opt("The last day of the month"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("You earn $60 this week. What happens to it?"),
        options=(
            _opt("It carries to next week's pay"),
            _opt("It is lost"),
            _opt("It is paid in cash"),
            _opt("You must ask Z for it"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("Which is true in the car?"),
        options=(
            _opt("Water and coffee are fine, but no eating and nothing that takes your eyes or hands off driving"),
            _opt("Nothing at all, not even water"),
            _opt("Eating is fine if it's quick"),
            _opt("Only coffee is allowed, not water"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("There's an accident. Nobody is hurt. Who do you call first?"),
        options=(
            _opt("Dispatch"),
            _opt("911"),
            _opt("Your family"),
            _opt("The school"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("Your partner gave you a camera for your van. What do you do?"),
        options=(
            _opt("Keep it on every ride"),
            _opt("Turn it off when convenient"),
            _opt("Only use it if dispatch asks"),
            _opt("Every driver must have a camera, so it doesn't matter"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("When do you wear your vest and put your placard in the window?"),
        options=(
            _opt("Every ride"),
            _opt("Only the first ride of the day"),
            _opt("Only if dispatch asks"),
            _opt("Only if it's your first week"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("You wake up sick at 5am. Your ride is at 6:40. What do you do?"),
        options=(
            _opt("Call dispatch immediately — the second you know"),
            _opt("Wait to see if you feel better"),
            _opt("Have a friend drive without telling dispatch"),
            _opt("Text the school directly"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("Your registration expired yesterday and you haven't renewed it. Can you drive today?"),
        options=(
            _opt("No — an expired document means no driving, by contract, no exceptions"),
            _opt("Yes, as long as you renew by the end of the week"),
            _opt("Yes, if dispatch doesn't ask"),
            _opt("Only on short routes"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("You are paid as a 1099 contractor. What does that mean about taxes?"),
        options=(
            _opt("No taxes are taken out — you owe your own taxes"),
            _opt("Taxes are taken out automatically"),
            _opt("You never owe any taxes"),
            _opt("Only Z pays your taxes"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("Can you bring your own kids or a friend along on a ride?"),
        options=(
            _opt("No — only the assigned student rides in the car"),
            _opt("Yes, if there's room"),
            _opt("Yes, but only on the way home"),
            _opt("Only if dispatch doesn't ask"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("The notes say a child needs a car seat. What do you do?"),
        options=(
            _opt("Use the car seat every time, no exceptions"),
            _opt("Skip it if the ride is short"),
            _opt("Only use it if the parent asks"),
            _opt("Use a seat belt instead"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("EverDriven's dispatch calls you directly during a ride. What do you do?"),
        options=(
            _opt("Answer, follow their directions, then tell Maz dispatch"),
            _opt("Don't answer, only Maz dispatch can call you"),
            _opt("Answer but ignore what they say"),
            _opt("Hang up and call Z"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("The app won't let you start a ride. What do you do?"),
        options=(
            _opt("Screenshot it and call dispatch before you drive"),
            _opt("Drive anyway, the app will catch up"),
            _opt("Wait until the ride is over to report it"),
            _opt("Restart your phone and skip the ride"),
        ),
        correct=0,
    ),
    QuizQuestion(
        question=_opt("You drive the week of September 14. When does that money land?"),
        options=(
            _opt("Friday, October 2 — two weeks after that week ends"),
            _opt("Friday, September 18 — the same week"),
            _opt("Friday, September 25 — one week later"),
            _opt("The last day of the month"),
        ),
        correct=0,
    ),
)


def course_content_public() -> dict:
    """JSON-safe course content for the public /training/{token} page.

    Includes quiz `correct` indices — this is a training comprehension quiz,
    not a proctored exam (the answers are effectively derivable from the
    module content itself); server-side enforcement of the pass threshold
    happens independently in record_certification()/validate below, so a
    client that fabricates its own quiz_score still gets rejected there.
    """
    return {
        "course_version": COURSE_VERSION,
        "pass_threshold_ratio": PASS_THRESHOLD_RATIO,
        "modules": [
            {
                "key": m.key,
                "title": m.title,
                "intro": m.intro,
                "blocks": [
                    {"lead": b.lead, "text": b.text} for b in m.blocks
                ],
            }
            for m in COURSE_MODULES
        ],
        "quiz": [
            {
                "question": q.question,
                "options": list(q.options),
                "correct": q.correct,
            }
            for q in QUIZ_QUESTIONS
        ],
    }


# ---------------------------------------------------------------------------
# Certification record helpers
# ---------------------------------------------------------------------------

def _latest_certification(db: Session, person_id: int):
    from backend.db.models import DriverCertification

    return (
        db.query(DriverCertification)
        .filter(DriverCertification.person_id == person_id)
        .order_by(DriverCertification.certified_at.desc(), DriverCertification.cert_id.desc())
        .first()
    )


def is_certified(db: Session, person_id: int) -> bool:
    """True iff the driver's latest certification row matches COURSE_VERSION."""
    latest = _latest_certification(db, person_id)
    if not latest:
        return False
    return latest.course_version == COURSE_VERSION


def needs_recert(db: Session, person_id: int) -> bool:
    """True iff the driver has certified before, but not on the current
    COURSE_VERSION — distinct from never-certified (is_certified=False,
    needs_recert=False for a driver who has simply never taken the course)."""
    latest = _latest_certification(db, person_id)
    if not latest:
        return False
    return latest.course_version != COURSE_VERSION


def record_certification(
    db: Session,
    person_id: int,
    quiz_score: int,
    quiz_total: int,
    signed_name: str,
    course_version: str = COURSE_VERSION,
):
    """Insert a new DriverCertification row. Caller (route handler) is
    responsible for having already validated quiz_score >= pass_threshold
    and signed_name being non-empty — this function does not re-validate,
    it only persists (mirrors record_* helper naming already used elsewhere
    in the codebase, e.g. onboarding autosend logging)."""
    from backend.db.models import DriverCertification

    row = DriverCertification(
        person_id=person_id,
        course_version=course_version,
        quiz_score=quiz_score,
        quiz_total=quiz_total,
        signed_name=signed_name,
        certified_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
