# UX Review — Summary

Reviewer: external UX tester, fresh account + fresh extension install, 14" laptop / 16:9 / Chrome. ~52 min walkthrough of homepage → signup → demo → extension setup → 10-min test run → pricing.

Legend: 🔴 = bug/blocker, 🟡 = friction/clarity, 🔵 = suggestion, ✅ = praise (nothing to do), ❓ = I can't tell what she's pointing at (video-only reference).

---

## Homepage (not formally in scope, but noted)

- [ ] **1. Nav gap** 🟡 ❓ — The split in the navigation reads as unintentional, like something is missing. Split navs work when they're deliberate (e.g. logo centered), but this one just looks broken. *Can't see which gap; need to look at the nav on a 14" screen.*
- [x] **2. CTA color** 🔵 ❓ — Wants the primary call-to-action to use the lime green accent so it draws the eye. Her conversion argument: "free trial, no card required" is a strong differentiator and deserves the loudest visual treatment on the page. *Doesn't name which button — presumably the hero CTA.*
- [ ] **3. Low-contrast text** 🟡 ❓ — Some text fades out / sits at low contrast, which will be hard for low-vision users. *Doesn't say which block; there may be a fade-out mask on a section.*
- [ ] **4. "1 / 2 / 3" numbering** 🔵 — The numbered items read like a step-by-step how-to-use guide, so the actual how-it-works section below loses its distinctiveness. Suggests replacing the numbers with small icons so the real process section stands out when scanning.
- [ ] **5. Testimonial marquee speed** 🟡 — Scrolls too fast to read even the first line, so it's distracting rather than persuasive. Slow it down enough that a user can catch an opening phrase and decide to stop.
- [ ] **6. Footer links blocked** 🔴 — The light/dark mode toggle sits over the footer links and makes them hard to click.

---

## Signup

- [x] **7. Username is case-sensitive** 🔴 — Her single biggest friction point, raised three separate times. She signed up with a capital "S", got logged out mid-onboarding, and spent a long time locked out trying lowercase, then her email address, then assuming she'd mistyped her password. Most sites treat usernames as case-insensitive; she nearly abandoned the account. *Note: commit `cb72ad5` says login/registration were made case-insensitive — worth confirming whether her recording predates that.*
- [x] **8. No password confirm or show/hide** 🟡 — The strength checklist is good, but there's no way to verify what she typed. A typo here is invisible until login fails, which costs far more friction than a second field or an eye toggle would. *Note: commit `cb72ad5` mentions show/hide toggles were added — again, may predate her test.*
- [ ] **9. Privacy policy / T&C links go nowhere useful** 🔴 ❓ — All the policy links open the same page in a new tab, so the user never actually sees the policies. She flagged this as must-fix before real users. *Says it opens "the same page" — I can't tell if it re-opens signup or one shared placeholder.*
- [x] **10. Login should accept email or username** 🔵 — People forget usernames. She tried her email in the username field and it was rejected. At minimum, the "incorrect username or password" error should mention case sensitivity if that behavior stays.

✅ **Good error prevention** — Can't proceed without accepting the checkboxes, which she liked.

---

## Interactive demo

- [ ] **11. "Ready to join Sarah" is misleading** 🟡 — Scanning, she thought she was joining a real video call, and the "your mic and camera are off" line made her expect a browser permission prompt. She only realized it was a demo once inside. Make it explicit up front that this is an interactive demo.
- [ ] **12. First hotkey run is too fast** 🟡 — On the first Ctrl+Shift+7 too much happened at once across two areas of the screen to absorb; on a second pass with context it felt fine. This is a first-run comprehension problem specifically.
- [ ] **13. Speed controls are too small / unlabeled** 🟡 ❓ — She found them late and guessed at what they meant. *"These" = the small speed buttons, also present on the homepage.*
- [ ] **14. Add an intro tooltip/popup** 🔵 — After the user chooses to start the demo, show a short overlay: this is an interactive demo, here's how to slow it down, here are the tour tips. She liked the existing tour tips and back navigation but didn't notice them at first.
- [x] **15. Post-"Leave" message flashes by** 🟡 ❓ — Some text with an underlined purple link appeared and vanished before she could read it. *Can't see what that message says.*

---

## Interview date screen

- [ ] **16. Add reassurance that they can practice beforehand** 🔵 — Reading "give us a date and we'll have it set up," she wanted explicit confirmation she could rehearse before the real interview. She framed this as the emotional core of the product: users are already anxious, and "what if I've installed it wrong" compounds that.
- [ ] **17. Time zones** 🟡 — The "email the evening before" promise needs a time zone (and possibly interview time), or international users get it on the wrong day.
- [ ] **18. No way back to the demo** 🔴 — If a user skips or leaves the demo, there's no back arrow or "back to demo" link. She called this a core heuristic violation (user control and freedom / clearly marked exits).

✅ **Liked the clarity** on what the product does and doesn't do, and the calendar picker.

---

## Chrome extension setup

- [ ] **19. "Skip setup" needs a confirmation** 🔵 — She expected a warning that the extension is essential; she avoided clicking it in case it cost her her place.
- [x] **20. Five steps at once is overwhelming** 🟡 — For non-technical users, seeing the whole manual install laid out reads as "I can't be bothered." Suggests revealing one step at a time, like the previous screen's overlay approach.
- [x] **21. Break up the instruction paragraph** 🔵 — Add a line break so it's two shorter paragraphs and more inviting to read.
- [ ] **22. Step 2 messaging is unclear** 🟡 — She had to re-read the tab-lock instructions several times and still wasn't sure whether something extra was required, or what the 10-second buffer was for.
- [ ] **23. Clicking a practice-problem link auto-completes the step** 🟡 — She clicked a coding site link, went back to check the hotkeys, and found the step already ticked and the flow moved on. She had no idea what she'd done or why.
- [ ] **24. Not obvious you can go back to a previous step** 🟡 — The hover state changes, but nothing signals the steps are clickable to reopen.
- [ ] **25. Hotkeys shown before the app is running** 🔴 — The biggest confusion of the setup section. Seeing Ctrl+Shift+7/8/9 listed under a step, she went to the coding site and pressed them repeatedly; nothing happened, because the trial hadn't started. Either remove the hotkey list from that step or add a line saying "you don't need these yet."

✅ **The install instructions themselves were clear and easy to follow.**

---

## Test run / phone view

- [ ] **26. Unclear where answers appear** 🟡 — The demo shows the phone panel beside the video call, so she expected the app to overlay into her Google Meet/Zoom window. She only understood it's a genuinely separate device after reaching the QR step.
- [ ] **27. "Prop your phone up" tip is buried** 🔵 — She called this one of the most important instructions in the product (users can't be caught glancing sideways or down) and it's easy to skim past. Suggests a lightbulb icon or similar emphasis.
- [ ] **28. Can't scroll back through past answers** 🟡 — She tried to scroll up on the phone view and couldn't.
- [ ] **29. Small, low-contrast text on the phone view** 🟡 — Specifically the "Your answer" and "Hotkeys" headings.
- [ ] **30. Unlabeled controls** 🟡 ❓ — There's a Clear button (which worked, and wiped everything) plus a three-dot control with + and − either side that she couldn't interpret. *I assume the +/− is font size; she had no way to tell.*
- [x] **31. Typing mode and the on/off toggle don't work for her** 🔴 — Ctrl+Shift+5 and Ctrl+Shift+9 produced nothing she could see, tried repeatedly across tabs. She also flagged the copy "toggle on/off" as meaningless: toggle *what*? This was the one functional area she left unresolved.
- [ ] **32. Session link expired mid-test** 🟡 — "Link expired, click refresh to get a new one." Not a complaint, but she noted it fired because she was taking her time narrating.
- [x] **33. Got logged out mid-onboarding once** 🔴 ❓ — Around the extension install step, and she couldn't reproduce it. *No further detail — worth checking session/cookie handling around that step.*

✅ **Screen capture, voice capture, and instant replay all worked as expected** — Instant replay correctly identified a non-coding YouTube video, then correctly captured a real interview question from a coding video and produced a full solution. She said this is where the product's value really lands.

---

## Post-trial + pricing

- [x] **34. "Key bindings" vs "hotkeys"** 🟡 — Two terms for the same thing across screens; pick one.
- [ ] **35. Sell the practice angle harder** 🔵 — On the plans screen, explicitly say they can rehearse with a friend on a mock call before the real interview. She believes fear of getting caught is the main objection for this audience, and practice is the answer to it.
- [ ] **36. No way back from the interview-context link** 🔵 — She had to use the browser back button to return to the trial-end page.
- [ ] **37. No light/dark toggle during onboarding** 🔵 — It exists on the homepage but disappears afterward; someone struggling to read low-contrast text has no recourse. Add it to the nav.
- [ ] **38. Show the regular price next to the intro deal** 🔵 — £2/one session vs £10/three sessions reads oddly without an anchor. Show what it normally costs so the new-member deal is obviously a deal.
- [ ] **39. Back button placement** 🟡 — There is a back control, but it's not where users look; move it to conventional top-left nav position.

✅ **Strong pricing framing** — She thinks the price is "ridiculously cheap" for the value and that the job-pays-for-it argument is a strong selling point.

---

## Closing / overall

- **Confidence:** despite no technical background, she'd feel confident setting the app up for a real interview — with the exception of typing mode and the on/off toggle, which she never got working.
- **Repetition:** she found no meaningful repetition, and liked that most steps are skippable.
- **If drop-off shows up at the 5-step install screen:** she'd A/B a one-step-at-a-time layout with a progress bar (leaning on completion bias), but wouldn't rebuild it preemptively — measure first.
- **Acknowledged** that the Web Store launch removes the manual install steps entirely, which resolves a lot of this section on its own.

---

## Suggested priority

**Fix first:** #7 case-sensitive username (if not already shipped), #9 policy links, #31 typing mode / toggle, #25 premature hotkeys, #6 footer overlap, #18 no way back to demo, #33 mystery logout.

**High value, low cost:** #34 terminology, #21 paragraph break, #27 tip emphasis, #30 label the +/− controls, #38 price anchor, #39 back button placement.

**Design work:** #2 CTA accent color, #4 replace 1-2-3 with icons, #5 marquee speed, #20 progressive step disclosure, #37 dark mode toggle in nav.
