# InterviewAce — launch & marketing notes

Working notes, August 2026. Pre-launch, awaiting Chrome Web Store approval.

---

## 1. The framing decision

Everything below hangs off this. Decide it deliberately before anything ships.

"ChatGPT can't follow you into interviews, we can" is a great hook and also a written statement of purpose. Consequences:

- **CWS review.** Your permission set (screen capture, audio, injection on third-party domains) makes manual review likely. Marketing that frames the product as defeating an assessment gives a reviewer an easy reason to reject. Rejections are harder to reverse than to avoid.
- **Listing copy and campaign copy shouldn't diverge sharply.** That gap is itself a problem if anyone looks.
- **Countermeasures.** HireVue, CodeSignal and similar have proctoring teams. Being the loudest target moves you up their list. A viral week can cost you the product.
- **Legal.** UK recording consent in interviews, and whether the marketing induces candidates toward something an employer could treat as fraud. Worth a few hundred quid of real advice before the van rolls. I'm not a lawyer.

Two viable framings — "preparation and confidence" vs "beat the system". They reach different people and survive differently. Pick one on purpose.

---

## 2. Launch scope: narrow, not generic

Launch software/tech only. Not close.

- Specific copy converts. "Handles the follow-up when they ask you to optimise it" beats "helps in your interview".
- The demo is credible to someone who's sat the interview. A generic behavioural demo could be anything.
- **Clean retention read.** Mixed traffic means you can't tell whether weak conversion is a bad product or the wrong audience. Worst thing to be uncertain about immediately post-launch.
- Every channel you have is already segment-matched (Leeds CS, technical creators, coding Discords).

**Keep generic:** the architecture (question banks, prompt scaffolding, demo content, onboarding copy as config, not code — cheap now, expensive retrofitted) and the brand.

**Widen on signal, not date:** trusted retention/conversion numbers in software, plus unprompted inbound from another segment.

---

## 3. Sequencing

CWS review is out of your hands. Days to weeks, possibly longer with manual review. It may outlast the coding.

**Use the wait for the 20-user test.** Not the campaign. Twenty people actively interviewing. Watch: install → activate in a real interview → return for a second → pay. That's days, not weeks, and it tells you what a campaign can't.

Marketing groundwork during the wait = thinking, not executing. Who the first hundred users are, where they already are, what the message is.

**Guard against polish-as-avoidance.** Whatever the infra list is now, that's the list. New items go in a post-launch pile unless genuinely blocking. The failure mode is CWS extends, two weeks becomes four, launch slips indefinitely.

---

## 4. Existing channels — notes

**Referral program (15–25%).** Strongest asset. Build the launch around it, not as an add-on. The highest-value referrer isn't a Discord admin, it's a user who just got an offer — genuine enthusiasm, natural story. Make the payout prompt fire at that moment, and show the amount *before* they refer.

**Discord.** Be selective. Large engineering servers have mods who'll read this as cheating; a public ban is worse than no partnership. Job-hunting and grad-scheme servers are softer ground.

**Universities / van.** Leeds first, you have standing. Timing dominates — a van in June is a van nobody sees. Check whether the CS car park is university land; you'll be moved on within the hour, which might itself be the content.

**Creators.** NeetCode and Fireship are the wrong fit, not just expensive — their audiences take pride in preparing properly, and the association could damage them, so they'll likely decline. Smaller grad-jobs and career-advice creators are cheaper, warmer, better matched.

**LinkedIn outrage.** Will work. Invites platform enforcement and countermeasures. See section 1.

**UGC / slideshows / paid social.** No strong notes, proceed as planned.

---

## 5. New ideas, ranked

### Free AI interviewer web app — top pick
Reverse the product. Free web app where an AI interviews *you*: pick a company and role, it grills you the way that company actually does, scores you, shows where you blanked. Shareable scorecard.

Solves several problems at once:
- Web app, so **no CWS gate** — can launch during the wait
- Completely defensible; marketable in places the extension isn't, including creators who'd reject the extension
- Captures emails from exactly the people with interviews coming
- Scorecard is the viral object ("the AI Goldman interviewer gave me 4/10")
- Feeds and is fed by the question data asset

Roughly a week on your existing stack (Whisper, Claude, real-time infra already running).

### AI-allowed interviews tracker
Public, maintained, sourced list of employers who permit or encourage AI use in interviews. Shopify's leadership publicly mandated AI fluency; a scattering of startups run AI-permitted interviews. Nobody has organised this into an artifact.

Linkable, citable by journalists, employers want to be added (signals modernity). Repositions you from cheat vendor to standard-bearer of an obvious coming shift, and gives the product a legitimate home: "the tool for AI-allowed interviews" is a category you'd own.

### Coaches and recruiters
Both get paid when candidates pass. Nobody markets to them.
- **Interview coaches** charge high hourly rates to desperate people; a pragmatic subset would use it in sessions or refer through your commission tiers.
- **Individual agency recruiters** are paid on placement and already coach candidates, share question banks, rehearse answers. No agency can touch this officially, but a referral link travels quietly.

Your tiered affiliate structure was built for these more than for Discord admins.

### Sympathetic segments
Interview anxiety, neurodivergence, international students. Enormous, underserved, largely unmarketed-to by this category. Real-time prompting when your mind goes blank is genuinely accommodation-shaped. Language pressure for international students is a real and sympathetic problem.

**Condition: it has to be sincere.** Real landing page, real understanding, ideally real users from that group telling the story. These communities detect cynical framing instantly and the backlash is worse than the LinkedIn kind.

### Cheap attention layer
Small, mispriced placements reaching exactly your demographic:
- GitHub interview-prep repos with huge traffic whose maintainers accept sponsors
- Job-hunt and CS-career newsletters
- Student meme pages (IG/X) — a shoutout costs less than a tank of diesel
- University society sponsorships — CS/finance/consulting societies are broke; ~£200 buys the mailing list and a logo
- **The Tab** — student press, actively wants controversy, reaches the whole UK market. "Leeds grad builds AI that whispers answers in your interview" is a story they'd run free. Probably worth more than the van.

### Calendar marketing
Demand is violently seasonal and almost nobody exploits it.
- **IB:** applications open ~late June–July, rolling, some effectively close by Sept. September is already late here.
- **Broad grad market:** Sept–early Oct, clustered in the first 2–3 weeks of September.
- **Rolling assessment** means candidates apply early — panic starts before published deadlines.
- **Your demand peak lags applications by ~4–8 weeks** (you're used at the interview, not the application). So Oct–Dec, then a second surge Jan–Feb for spring weeks.
- Also: layoff news cycles (timely vs ghoulish is a thin line), results day, assessment centre dates and venues (candidates post these publicly).
- Tech is looser than finance/consulting — real seasonality but softer.

*Dates shift each cycle — verify against actual employer pages and Leeds careers service before building a calendar.*

### Outcome-based pricing as the hook
"Free until you get hired" / offer guarantee. The pricing *is* the story — gets shared as a story, not an ad, and screams confidence in a category where the core doubt is "does this actually work." Needs abuse-proofing and real unit economics work.

### Two small ones
- **Competitor SEO.** Cluely's viral spend generates search volume you can catch with comparison pages. Their breach history writes your copy.
- **WhatsApp over Discord** for international student cohorts — entire placement seasons are organised in group chats. Relevant if you ever look at India off-campus, where volume is enormous and Cluely barely exists.

---

## 6. Category expansion (later)

Ranked by **format proximity**, not market size. You're strongest where questions are predictable in shape, answers are structured, and the candidate is under time pressure.

| Tier | Category | Why |
|---|---|---|
| 1 | **Consulting** | Most structured non-technical format. Market sizing, profitability frameworks, live arithmetic under pressure. Same universities, same autumn cycle, same channels. Minimal adaptation. |
| 1 | **Finance** | Near-deterministic question set (DCF, three statements, accretion/dilution). Extremely motivated, well-paid candidates. Earlier calendar extends your season backwards. |
| 2 | **Product management** | Shares your existing audience. Estimation, product sense, prioritisation. Candidates often hedge PM/eng. |
| 3 | **Data & analytics** | SQL, stats, case-style analysis. Basically an extension of what you have. |
| 3 | **Law** | Training contract interviews, commercial awareness, predictable format. |
| 3 | **Sales** | Mock pitches, objection handling. Zero cultural resistance to tools that help them win. |
| ? | **Medicine / healthcare** | Structurally ideal (MMIs, scenario-based, known ethical frameworks, huge motivated pool). But the ethical objection lands hardest here and professional bodies are unforgiving. Reputational risk, not technical. |

**Avoid:** behavioural-only rounds, culture fit, senior leadership hiring. The product can prompt structure but can't supply your actual experience — users churn fast.

**Possibly cheaper than any vertical:** geographic expansion. Same technical interview in Germany, India, Singapore. Reuses everything, into markets Cluely isn't seriously working.

---

## 7. Recommendation

**Pick two.**

1. The free AI interviewer — it compounds, dodges the CWS dependency, and is defensible everywhere.
2. One cheap-attention test (The Tab or meme pages) to learn what your actual cost per install is.

Everything else is a backlog. A good one. But breadth is how solo launches die.