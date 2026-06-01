# Environment Variable Config Reference

All server configuration is controlled via environment variables prefixed with
`ENSHROUDED_`. The conversion from env var to JSON key follows these rules:

- The `ENSHROUDED_` prefix is stripped
- `__` (double underscore) creates nested keys
- `_` (single underscore) in a segment is converted to camelCase
  (e.g. `ENABLE_VOICE_CHAT` → `enableVoiceChat`)

## Top-level keys

| JSON Key             | Type             | Default               | Env Var                           |
| -------------------- | ---------------- | --------------------- | --------------------------------- |
| `name`               | string           | `"Enshrouded Server"` | `ENSHROUDED_NAME`                 |
| `ip`                 | string           | `"0.0.0.0"`           | `ENSHROUDED_IP`                   |
| `queryPort`          | integer          | `15637`               | `ENSHROUDED_QUERY_PORT`           |
| `slotCount`          | integer          | `16`                  | `ENSHROUDED_SLOT_COUNT`           |
| `saveDirectory`      | string           | `"./savegame"`        | `ENSHROUDED_SAVE_DIRECTORY`       |
| `logDirectory`       | string           | `"./logs"`            | `ENSHROUDED_LOG_DIRECTORY`        |
| `tags`               | array of strings | `[]`                  | `ENSHROUDED_TAGS`                 |
| `enableVoiceChat`    | bool             | `false`               | `ENSHROUDED_ENABLE_VOICE_CHAT`    |
| `enableTextChat`     | bool             | `false`               | `ENSHROUDED_ENABLE_TEXT_CHAT`     |
| `voiceChatMode`      | string           | `"Proximity"`         | `ENSHROUDED_VOICE_CHAT_MODE`      |
| `gameSettingsPreset` | string           | `"Default"`           | `ENSHROUDED_GAME_SETTINGS_PRESET` |

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

All `gameSettings.*` keys use `__` for nesting:

| JSON Key                            | Type    | Default                  | Env Var                                                          |
| ----------------------------------- | ------- | ------------------------ | ---------------------------------------------------------------- |
| `playerHealthFactor`                | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__PLAYER_HEALTH_FACTOR`                 |
| `playerManaFactor`                  | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__PLAYER_MANA_FACTOR`                   |
| `playerStaminaFactor`               | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__PLAYER_STAMINA_FACTOR`                |
| `playerBodyHeatFactor`              | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__PLAYER_BODY_HEAT_FACTOR`              |
| `playerDivingTimeFactor`            | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__PLAYER_DIVING_TIME_FACTOR`            |
| `enableDurability`                  | bool    | `true`                   | `ENSHROUDED_GAME_SETTINGS__ENABLE_DURABILITY`                    |
| `enableStarvingDebuff`              | bool    | `false`                  | `ENSHROUDED_GAME_SETTINGS__ENABLE_STARVING_DEBUFF`               |
| `foodBuffDurationFactor`            | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__FOOD_BUFF_DURATION_FACTOR`            |
| `fromHungerToStarving`              | integer | `600000000000`           | `ENSHROUDED_GAME_SETTINGS__FROM_HUNGER_TO_STARVING`              |
| `shroudTimeFactor`                  | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__SHROUD_TIME_FACTOR`                   |
| `tombstoneMode`                     | string  | `"AddBackpackMaterials"` | `ENSHROUDED_GAME_SETTINGS__TOMBSTONE_MODE`                       |
| `enableGliderTurbulences`           | bool    | `true`                   | `ENSHROUDED_GAME_SETTINGS__ENABLE_GLIDER_TURBULENCES`            |
| `weatherFrequency`                  | string  | `"Normal"`               | `ENSHROUDED_GAME_SETTINGS__WEATHER_FREQUENCY`                    |
| `fishingDifficulty`                 | string  | `"Normal"`               | `ENSHROUDED_GAME_SETTINGS__FISHING_DIFFICULTY`                   |
| `miningDamageFactor`                | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__MINING_DAMAGE_FACTOR`                 |
| `plantGrowthSpeedFactor`            | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__PLANT_GROWTH_SPEED_FACTOR`            |
| `resourceDropStackAmountFactor`     | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__RESOURCE_DROP_STACK_AMOUNT_FACTOR`    |
| `factoryProductionSpeedFactor`      | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__FACTORY_PRODUCTION_SPEED_FACTOR`      |
| `perkUpgradeRecyclingFactor`        | float   | `0.5`                    | `ENSHROUDED_GAME_SETTINGS__PERK_UPGRADE_RECYCLING_FACTOR`        |
| `perkCostFactor`                    | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__PERK_COST_FACTOR`                     |
| `experienceCombatFactor`            | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__EXPERIENCE_COMBAT_FACTOR`             |
| `experienceMiningFactor`            | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__EXPERIENCE_MINING_FACTOR`             |
| `experienceExplorationQuestsFactor` | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__EXPERIENCE_EXPLORATION_QUESTS_FACTOR` |
| `randomSpawnerAmount`               | string  | `"Normal"`               | `ENSHROUDED_GAME_SETTINGS__RANDOM_SPAWNER_AMOUNT`                |
| `aggroPoolAmount`                   | string  | `"Normal"`               | `ENSHROUDED_GAME_SETTINGS__AGGRO_POOL_AMOUNT`                    |
| `enemyDamageFactor`                 | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__ENEMY_DAMAGE_FACTOR`                  |
| `enemyHealthFactor`                 | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__ENEMY_HEALTH_FACTOR`                  |
| `enemyStaminaFactor`                | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__ENEMY_STAMINA_FACTOR`                 |
| `enemyPerceptionRangeFactor`        | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__ENEMY_PERCEPTION_RANGE_FACTOR`        |
| `bossDamageFactor`                  | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__BOSS_DAMAGE_FACTOR`                   |
| `bossHealthFactor`                  | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__BOSS_HEALTH_FACTOR`                   |
| `threatBonus`                       | float   | `1`                      | `ENSHROUDED_GAME_SETTINGS__THREAT_BONUS`                         |
| `pacifyAllEnemies`                  | bool    | `false`                  | `ENSHROUDED_GAME_SETTINGS__PACIFY_ALL_ENEMIES`                   |
| `tamingStartleRepercussion`         | string  | `"LoseSomeProgress"`     | `ENSHROUDED_GAME_SETTINGS__TAMING_STARTLE_REPERCUSSION`          |
| `dayTimeDuration`                   | integer | `1800000000000`          | `ENSHROUDED_GAME_SETTINGS__DAY_TIME_DURATION`                    |
| `nightTimeDuration`                 | integer | `720000000000`           | `ENSHROUDED_GAME_SETTINGS__NIGHT_TIME_DURATION`                  |
| `curseModifier`                     | string  | `"Normal"`               | `ENSHROUDED_GAME_SETTINGS__CURSE_MODIFIER`                       |

## User Groups (`userGroups` array)

The `userGroups` field is an array of objects. There are two ways to populate it.

### Method 1: Numeric Indexing

Use `__<N>__` to directly index into the array. The `name` field must be
explicitly set.

```env
ENSHROUDED_USER_GROUPS__0__NAME=Admin
ENSHROUDED_USER_GROUPS__0__PASSWORD=Admino
ENSHROUDED_USER_GROUPS__0__CAN_KICK_BAN=true
ENSHROUDED_USER_GROUPS__0__RESERVED_SLOTS=1

ENSHROUDED_USER_GROUPS__1__NAME=Friend
ENSHROUDED_USER_GROUPS__1__PASSWORD=Friendo
ENSHROUDED_USER_GROUPS__1__CAN_KICK_BAN=false
ENSHROUDED_USER_GROUPS__1__CAN_ACCESS_INVENTORIES=true
```

This produces:

```json
[
  { "name": "Admin", "password": "Admino", "canKickBan": true, "reservedSlots": 1 },
  { "name": "Friend", "password": "Friendo", "canKickBan": false, "canAccessInventories": true }
]
```

Available fields per user group:

| Field                  | Type    | Default |
| ---------------------- | ------- | ------- |
| `name`                 | string  | —       |
| `password`             | string  | —       |
| `canKickBan`           | bool    | `false` |
| `canAccessInventories` | bool    | `false` |
| `canEditWorld`         | bool    | `false` |
| `canEditBase`          | bool    | `false` |
| `canExtendBase`        | bool    | `false` |
| `reservedSlots`        | integer | `0`     |

### Method 2: Name-keyed dicts

Use group names as dict keys. The `name` field is **automatically injected**
from the env var key.

```env
ENSHROUDED_USER_GROUPS__ADMIN__PASSWORD=Admino
ENSHROUDED_USER_GROUPS__ADMIN__CAN_KICK_BAN=true
ENSHROUDED_USER_GROUPS__FRIEND__PASSWORD=Friendo
```

This produces the same result as Method 1 — the config system detects that
`userGroups` is an array in the base config (or that the dict looks
name-keyed) and converts `{"admin": {"password": "Admino"}}` into
`[{"name": "admin", "password": "Admino"}]`.

> **Quirk**: when using Method 2, the `name` value is derived from the env
> key node, **not** from a `name` field in the value. If you set both
> `ENSHROUDED_USER_GROUPS__ADMIN__NAME=Custom`, the `name` from the key
> (`"admin"`) takes precedence and overwrites it.

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
