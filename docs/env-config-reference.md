# Environment Variable Config Reference

Set every server option without editing the JSON file.

## Top-level settings

| Env Var                           | Default               | Valid values / Range                           | Type             | Description                                              | JSON Key             |
| --------------------------------- | --------------------- | ---------------------------------------------- | ---------------- | -------------------------------------------------------- | -------------------- |
| `ENSHROUDED_NAME`                 | `"Enshrouded Server"` | —                                              | string           | Name shown in the Join menu server list.                 | `name`               |
| `ENSHROUDED_IP`                   | `"0.0.0.0"`           | —                                              | string           | Bind address; change only with a specific reason.        | `ip`                 |
| `ENSHROUDED_QUERY_PORT`           | `15637`               | —                                              | integer          | Server query port; change with caution.                  | `queryPort`          |
| `ENSHROUDED_SLOT_COUNT`           | `16`                  | `1–16`                                         | integer          | Maximum number of players allowed on the server.         | `slotCount`          |
| `ENSHROUDED_SAVE_DIRECTORY`       | `"./savegame"`        | —                                              | string           | Directory that stores the world savegame.                | `saveDirectory`      |
| `ENSHROUDED_LOG_DIRECTORY`        | `"./logs"`            | —                                              | string           | Directory that stores the server logfiles.               | `logDirectory`       |
| `ENSHROUDED_TAGS`                 | `[]`                  | Any tag from the list below                    | array of strings | Server browser filter tags.                              | `tags`               |
| `ENSHROUDED_ENABLE_VOICE_CHAT`    | `false`               | `true / false`                                 | bool             | Switch voice chat on or off.                             | `enableVoiceChat`    |
| `ENSHROUDED_ENABLE_TEXT_CHAT`     | `false`               | `true / false`                                 | bool             | Switch text chat on or off.                              | `enableTextChat`     |
| `ENSHROUDED_VOICE_CHAT_MODE`      | `"Proximity"`         | `Proximity / Global`                           | string           | Proximity or server-wide voice chat.                     | `voiceChatMode`      |
| `ENSHROUDED_GAME_SETTINGS_PRESET` | `"Default"`           | `Default / Relaxed / Hard / Survival / Custom` | string           | Difficulty preset; `Custom` enables individual settings. | `gameSettingsPreset` |

`gameSettingsPreset` options:

- `Default` — all values at their defaults; the recommended setting for
  first-time players.
- `Relaxed` — fewer enemies, more resources and loot; base-building and light
  adventuring.
- `Hard` — more enemies, more aggressive; tougher combat.
- `Survival` — extra survival mechanics on top of more aggressive enemies.
- `Custom` — unlocks the individual settings under
  [Game Settings](#game-settings-nested).

Two array fields are omitted from the table:

- `userGroups` — default groups Admin, Friend, Guest, Visitor; see
  [User Groups](#user-groups-usergroups-array).
- `bans` — default `[]`. Manage it in-game via the Social tab or edit
  `enshrouded_server.json` while the server is stopped. Entries store
  `accountIDHash`, `displayName`, `characterName`, and `banDate` (unix
  timestamp).

### The `tags` field

The `tags` array is set via a JSON-encoded string:

```env
ENSHROUDED_TAGS=["English","Portuguese","Exploration","LookingForPlayers"]
```

The brackets `[` `]` trigger JSON array parsing. Quotes around individual
items are required.

#### Available tags

**Language** — `English`, `German`, `French`, `Italian`, `Japanese`, `Korean`,
`Polish`, `Portuguese`, `Russian`, `Spanish`, `Thai`, `Turkish`, `Ukrainian`,
`Chinese`, `Taiwanese`

**Playstyle** — `BaseBuilding` (construction/building focus),
`Exploration` (adventure focus), `Roleplay` (roleplaying oriented)

**Status** — `LookingForPlayers` (welcomes new players)

## Game Settings (nested)

These individual settings take effect when `gameSettingsPreset` is `Custom`.

> [!NOTE]
>
> - Env vars use `__` for nesting: `ENSHROUDED_GAME_SETTINGS__` plus the field
>   name (e.g. `ENSHROUDED_GAME_SETTINGS__PLAYER_HEALTH_FACTOR`).
> - Numbers outside the documented range are clamped to min/max; invalid text
>   prevents the server from booting.
> - `*Factor` values display as percentages in game.
> - Durations are integers in nanoseconds (ns); human units are shown next to
>   defaults. Raw day/night bounds: `120000000000` (2 min) to
>   `3600000000000` (60 min).

| Env Var                                                          | Default                  | Valid values / Range                                | Type         | Description                                                   | JSON Key                            |
| ---------------------------------------------------------------- | ------------------------ | --------------------------------------------------- | ------------ | ------------------------------------------------------------- | ----------------------------------- |
| `ENSHROUDED_GAME_SETTINGS__PLAYER_HEALTH_FACTOR`                 | `1`                      | `0.25–4`                                            | float        | Scales max player health.                                     | `playerHealthFactor`                |
| `ENSHROUDED_GAME_SETTINGS__PLAYER_MANA_FACTOR`                   | `1`                      | `0.25–4`                                            | float        | Scales max mana.                                              | `playerManaFactor`                  |
| `ENSHROUDED_GAME_SETTINGS__PLAYER_STAMINA_FACTOR`                | `1`                      | `0.25–4`                                            | float        | Scales max stamina.                                           | `playerStaminaFactor`               |
| `ENSHROUDED_GAME_SETTINGS__PLAYER_BODY_HEAT_FACTOR`              | `1`                      | `0.5–2`                                             | float        | Body-heat reserve before hypothermia in cold areas.           | `playerBodyHeatFactor`              |
| `ENSHROUDED_GAME_SETTINGS__PLAYER_DIVING_TIME_FACTOR`            | `1`                      | `0.5–2`                                             | float        | Initial oxygen and time available underwater.                 | `playerDivingTimeFactor`            |
| `ENSHROUDED_GAME_SETTINGS__ENABLE_DURABILITY`                    | `true`                   | `true / false`                                      | bool         | When `false`, weapons no longer break.                        | `enableDurability`                  |
| `ENSHROUDED_GAME_SETTINGS__ENABLE_STARVING_DEBUFF`               | `false`                  | `true / false`                                      | bool         | Starvation drains health until food or drink is consumed.     | `enableStarvingDebuff`              |
| `ENSHROUDED_GAME_SETTINGS__FOOD_BUFF_DURATION_FACTOR`            | `1`                      | `0.5–2`                                             | float        | Scales food buff durations.                                   | `foodBuffDurationFactor`            |
| `ENSHROUDED_GAME_SETTINGS__FROM_HUNGER_TO_STARVING`              | `600000000000` (10 min)  | `5–20 min`                                          | integer (ns) | Length of the hungry state before starvation sets in.         | `fromHungerToStarving`              |
| `ENSHROUDED_GAME_SETTINGS__SHROUD_TIME_FACTOR`                   | `1`                      | `0.5–2`                                             | float        | Time player characters can remain in the Shroud.              | `shroudTimeFactor`                  |
| `ENSHROUDED_GAME_SETTINGS__TOMBSTONE_MODE`                       | `"AddBackpackMaterials"` | `AddBackpackMaterials / Everything / NoTombstone`   | string       | Which backpack items are lost on death.                       | `tombstoneMode`                     |
| `ENSHROUDED_GAME_SETTINGS__ENABLE_GLIDER_TURBULENCES`            | `true`                   | `true / false`                                      | bool         | When off, gliders ignore air turbulences.                     | `enableGliderTurbulences`           |
| `ENSHROUDED_GAME_SETTINGS__WEATHER_FREQUENCY`                    | `"Normal"`               | `Disabled / Rare / Normal / Often`                  | string       | How often new weather phenomena appear.                       | `weatherFrequency`                  |
| `ENSHROUDED_GAME_SETTINGS__FISHING_DIFFICULTY`                   | `"Normal"`               | `VeryEasy / Easy / Normal / Hard / VeryHard`        | string       | Fish strength during the fishing minigame.                    | `fishingDifficulty`                 |
| `ENSHROUDED_GAME_SETTINGS__MINING_DAMAGE_FACTOR`                 | `1`                      | `0.5–2`                                             | float        | Mining damage: terraforming and resource yield per hit.       | `miningDamageFactor`                |
| `ENSHROUDED_GAME_SETTINGS__PLANT_GROWTH_SPEED_FACTOR`            | `1`                      | `0.25–2`                                            | float        | Plant growth speed.                                           | `plantGrowthSpeedFactor`            |
| `ENSHROUDED_GAME_SETTINGS__RESOURCE_DROP_STACK_AMOUNT_FACTOR`    | `1`                      | `0.25–2`                                            | float        | Materials per loot stack (chests, enemies, etc.).             | `resourceDropStackAmountFactor`     |
| `ENSHROUDED_GAME_SETTINGS__FACTORY_PRODUCTION_SPEED_FACTOR`      | `1`                      | `0.25–2`                                            | float        | Workshop production time.                                     | `factoryProductionSpeedFactor`      |
| `ENSHROUDED_GAME_SETTINGS__PERK_UPGRADE_RECYCLING_FACTOR`        | `0.5`                    | `0–1`                                               | float        | Runes returned when salvaging upgraded weapons.               | `perkUpgradeRecyclingFactor`        |
| `ENSHROUDED_GAME_SETTINGS__PERK_COST_FACTOR`                     | `1`                      | `0.25–2`                                            | float        | Runes required to upgrade weapons.                            | `perkCostFactor`                    |
| `ENSHROUDED_GAME_SETTINGS__EXPERIENCE_COMBAT_FACTOR`             | `1`                      | `0.25–2`                                            | float        | XP gained from combat.                                        | `experienceCombatFactor`            |
| `ENSHROUDED_GAME_SETTINGS__EXPERIENCE_MINING_FACTOR`             | `1`                      | `0–2`                                               | float        | XP gained from mining resources.                              | `experienceMiningFactor`            |
| `ENSHROUDED_GAME_SETTINGS__EXPERIENCE_EXPLORATION_QUESTS_FACTOR` | `1`                      | `0.25–2`                                            | float        | XP gained from exploration and quests.                        | `experienceExplorationQuestsFactor` |
| `ENSHROUDED_GAME_SETTINGS__RANDOM_SPAWNER_AMOUNT`                | `"Normal"`               | `Few / Normal / Many / Extreme`                     | string       | Amount of enemies in the world.                               | `randomSpawnerAmount`               |
| `ENSHROUDED_GAME_SETTINGS__AGGRO_POOL_AMOUNT`                    | `"Normal"`               | `Few / Normal / Many / Extreme`                     | string       | Enemies allowed to attack at the same time.                   | `aggroPoolAmount`                   |
| `ENSHROUDED_GAME_SETTINGS__ENEMY_DAMAGE_FACTOR`                  | `1`                      | `0.25–5`                                            | float        | Enemy damage; excludes bosses.                                | `enemyDamageFactor`                 |
| `ENSHROUDED_GAME_SETTINGS__ENEMY_HEALTH_FACTOR`                  | `1`                      | `0.25–4`                                            | float        | Enemy health; excludes bosses.                                | `enemyHealthFactor`                 |
| `ENSHROUDED_GAME_SETTINGS__ENEMY_STAMINA_FACTOR`                 | `1`                      | `0.5–2`                                             | float        | Enemy stamina; higher means slower to stun. Excludes bosses.  | `enemyStaminaFactor`                |
| `ENSHROUDED_GAME_SETTINGS__ENEMY_PERCEPTION_RANGE_FACTOR`        | `1`                      | `0.5–2`                                             | float        | Enemy sight and hearing range; excludes bosses.               | `enemyPerceptionRangeFactor`        |
| `ENSHROUDED_GAME_SETTINGS__BOSS_DAMAGE_FACTOR`                   | `1`                      | `0.2–5`                                             | float        | Boss attack damage.                                           | `bossDamageFactor`                  |
| `ENSHROUDED_GAME_SETTINGS__BOSS_HEALTH_FACTOR`                   | `1`                      | `0.2–5`                                             | float        | Boss health.                                                  | `bossHealthFactor`                  |
| `ENSHROUDED_GAME_SETTINGS__THREAT_BONUS`                         | `1`                      | `0.25–4`                                            | float        | Frequency of enemy attacks; excludes bosses.                  | `threatBonus`                       |
| `ENSHROUDED_GAME_SETTINGS__PACIFY_ALL_ENEMIES`                   | `false`                  | `true / false`                                      | bool         | Enemies don't attack until attacked; excludes bosses.         | `pacifyAllEnemies`                  |
| `ENSHROUDED_GAME_SETTINGS__TAMING_STARTLE_REPERCUSSION`          | `"LoseSomeProgress"`     | `KeepProgress / LoseSomeProgress / LoseAllProgress` | string       | Effect when wildlife is startled during taming.               | `tamingStartleRepercussion`         |
| `ENSHROUDED_GAME_SETTINGS__DAY_TIME_DURATION`                    | `1800000000000` (30 min) | `2–60 min`                                          | integer (ns) | Length of daytime.                                            | `dayTimeDuration`                   |
| `ENSHROUDED_GAME_SETTINGS__NIGHT_TIME_DURATION`                  | `720000000000` (12 min)  | `2–60 min`                                          | integer (ns) | Length of nighttime.                                          | `nightTimeDuration`                 |
| `ENSHROUDED_GAME_SETTINGS__CURSE_MODIFIER`                       | `"Normal"`               | `Easy / Normal / Hard`                              | string       | Shroud curse chance when attacked; Easy = off, Hard = double. | `curseModifier`                     |

## User Groups (`userGroups` array)

The `userGroups` field is an array of objects. The default config ships four
groups: Admin, Friend, Guest, Visitor (see [Default group presets](#default-group-presets)).

There are two ways to
populate it.

### Method 1: Numeric Indexing

Use `__<N>__` to directly index into the array. The `name` field must be
explicitly set.

```env
ENSHROUDED_USER_GROUPS__0__NAME=Admin
ENSHROUDED_USER_GROUPS__0__PASSWORD=AdminPassword
ENSHROUDED_USER_GROUPS__0__CAN_KICK_BAN=true
ENSHROUDED_USER_GROUPS__0__RESERVED_SLOTS=1

ENSHROUDED_USER_GROUPS__1__NAME=Friend
ENSHROUDED_USER_GROUPS__1__PASSWORD=FriendPassword
ENSHROUDED_USER_GROUPS__1__CAN_KICK_BAN=false
ENSHROUDED_USER_GROUPS__1__CAN_ACCESS_INVENTORIES=true
```

This produces:

```json
[
  { "name": "Admin", "password": "AdminPassword", "canKickBan": true, "reservedSlots": 1 },
  {
    "name": "Friend",
    "password": "FriendPassword",
    "canKickBan": false,
    "canAccessInventories": true
  }
]
```

### Method 2: Name-keyed dicts

Use group names as dict keys. The `name` field is **automatically injected**
from the env var key.

```env
ENSHROUDED_USER_GROUPS__ADMIN__PASSWORD=AdminPassword
ENSHROUDED_USER_GROUPS__ADMIN__CAN_KICK_BAN=true
ENSHROUDED_USER_GROUPS__FRIEND__PASSWORD=FriendPassword
```

This produces the same result as Method 1: the config system detects the alternate format and folds it into the `userGroups` array.

> [!NOTE]
> When using Method 2, the `name` value is derived from the env
> key node, **not** from a `name` field in the value.
>
> If you set both `ENSHROUDED_USER_GROUPS__ADMIN__NAME=Custom`, the `name` from the key
> (`"admin"`) takes precedence and overwrites it.

### Available fields per group

Rows use the Method 1 index form; with Method 2, replace `<N>` with the group
name (e.g. `ENSHROUDED_USER_GROUPS__ADMIN__CAN_KICK_BAN`).

| Env Var                                               | Default | Valid values / Range | Type    | Description                                             | JSON Key               |
| ----------------------------------------------------- | ------- | -------------------- | ------- | ------------------------------------------------------- | ---------------------- |
| `ENSHROUDED_USER_GROUPS__<N>__NAME`                   | —       | —                    | string  | Group name; required with Method 1.                     | `name`                 |
| `ENSHROUDED_USER_GROUPS__<N>__PASSWORD`               | —       | —                    | string  | Password granting this group's permissions.             | `password`             |
| `ENSHROUDED_USER_GROUPS__<N>__CAN_KICK_BAN`           | `false` | `true / false`       | bool    | Kick or permanently ban other players.                  | `canKickBan`           |
| `ENSHROUDED_USER_GROUPS__<N>__CAN_ACCESS_INVENTORIES` | `false` | `true / false`       | bool    | Chests, factories, and containers in player bases.      | `canAccessInventories` |
| `ENSHROUDED_USER_GROUPS__<N>__CAN_EDIT_WORLD`         | `false` | `true / false`       | bool    | Terraform or destroy areas in the open world.           | `canEditWorld`         |
| `ENSHROUDED_USER_GROUPS__<N>__CAN_EDIT_BASE`          | `false` | `true / false`       | bool    | Build, terraform, and manage water in player bases.     | `canEditBase`          |
| `ENSHROUDED_USER_GROUPS__<N>__CAN_EXTEND_BASE`        | `false` | `true / false`       | bool    | Add, remove, and upgrade Flame Altars.                  | `canExtendBase`        |
| `ENSHROUDED_USER_GROUPS__<N>__RESERVED_SLOTS`         | `0`     | —                    | integer | Seats held back for this group when the server is full. | `reservedSlots`        |

`canAccessInventories` only covers objects in player bases; open-world
treasure chests stay accessible regardless.

When a group has 1 or more reserved slots, the lobby shows as "full" to
players in other groups who would fill the remaining session slots — so
Admins or Friends can still join a busy server.

### Default group presets

| Permission             | Admin | Friend | Guest | Visitor |
| ---------------------- | ----- | ------ | ----- | ------- |
| `canKickBan`           | true  | false  | false | false   |
| `canAccessInventories` | true  | true   | false | false   |
| `canEditWorld`         | true  | true   | true  | false   |
| `canEditBase`          | true  | true   | false | false   |
| `canExtendBase`        | true  | false  | false | false   |
| `reservedSlots`        | 0     | 0      | 0     | 0       |

- **Admin** — base changes, containers, and kick/ban allowed.
- **Friend** — base changes and containers allowed.
- **Guest** — no base changes, no containers.
- **Visitor** — no base changes, no containers, no world changes outside
  bases.

All groups except Visitor have full access to the game world outside player
bases (combat, gathering, quests).

> [!IMPORTANT]
> Presets are only generated when `enshrouded_server.json` is freshly created
> (Enshrouded newer than Update 2, 2024-06-05).
>
> A fresh config gets randomized passwords. If an old top-level `password` is detected, only a `default` group
> is created with Friend-level permissions.

## Conversion rules from env var to JSON key

This is how enshctl converts environment variables to JSON keys. May be useful for any new setting not listed in the table above.

- The `ENSHROUDED_` prefix is stripped
- `__` (double underscore) creates nested keys
- `_` (single underscore) in a segment becomes camelCase
  (e.g. `ENABLE_VOICE_CHAT` → `enableVoiceChat`)

## Value type auto-detection

Values auto-detect their type:

| Env Value        | Parsed As   |
| ---------------- | ----------- |
| `true` / `false` | bool        |
| `42`             | integer     |
| `3.14`           | float       |
| `["a","b","c"]`  | JSON array  |
| `{"key": "val"}` | JSON object |
| everything else  | string      |

## Debugging

Print the generated config without starting the server:

```bash
enshctl debug-config
```

Docker:

```bash
docker run --rm --env-file .env enshctl debug-config
```

Compose:

```bash
docker compose -f docker-compose.yml run --rm enshrouded debug-config
```
