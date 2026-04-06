# TODO / Roadmap

Future features for the MLB The Show Market Tracker.

---

## Squad Builder

Build out a tool that lets users construct a Diamond Dynasty squad and see:

- Position-by-position slot filling with card search and filtering
- Team chemistry / budget constraint tracking in stubs
- Export/share a squad loadout

**Data needed:** card metadata already exists (`cards` table). Needs a UI layer for slot assignment and a way to persist/share squads (could start as client-side state, no backend required initially).

---

## Account Integration — Personal Team & Mission Grinder

Allow users to connect their MLB The Show account to see:

- Their current roster and which cards they own
- Which missions they have active and what cards/stats are needed to complete them
- Market opportunities specific to them — e.g. "you need 50 HR with a Gold 1B, here are the cheapest options currently on the market"
- Stub budget tracking against their actual in-game balance

**Data needed:** MLB The Show does not have an official account API — will need to investigate whether there is an unofficial/community API or if this requires manual input (user enters their collection).

---

## Player Stats & Attributes

Pull and store actual in-game player attribute stats (not just market prices), including:

- Hitting: Contact vs L/R, Power vs L/R, Vision, Clutch
- Pitching: Stamina, H/9, K/9, BB/9, HR/9, Velocity, Break
- Fielding: Speed, Arm, Fielding rating

**Data needed:** the `/apis/items.json` endpoint returns full attribute data — it is already being fetched but only card metadata (name, OVR, rarity, position) is currently stored. Needs schema additions to `cards` table and a re-fetch.

**Unlocks:**

### Player Comparison Tool
Side-by-side attribute comparison between two or more cards. Filter by position, rarity, price range. Useful for finding value cards with similar stats to expensive ones.

### Power Rankings
Rank cards within a position by a composite score (weighted attribute formula, configurable by the user). Show where each card sits on a price-vs-performance curve to highlight over/undervalued cards relative to their stats.

---

## Other Ideas / Smaller Enhancements

- **External shock annotations** on trend charts — mark events like stub sales, new card drops, program releases, or game releases to non-pre-orders
- **Watchlist** — user can pin cards to a personal watchlist and get a dedicated view of their price movement
- **Flip queue** — ranked list of currently actionable flips sorted by expected profit, with one-click link to the in-game listing
- **Historical purge-aware charting** — ensure the `all` timerange on card history charts correctly uses the twice-daily landmark rows for older data, rather than showing gaps
