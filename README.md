# UK Train Times

A [Home Assistant](https://www.home-assistant.io/) integration that shows when your next train leaves, using the [Realtime Trains](https://www.realtimetrains.co.uk/) API (`data.rtt.io`).

Add one **route** (a from station and a to station) per journey you care about. Each route becomes a device with these entities:

| Entity | Description |
|---|---|
| Expected departure | Realtime departure time of the next train, falling back to the scheduled time when no forecast is published |
| Scheduled departure | Timetabled departure time of the next train |
| Delay | Minutes the next train is running late (0 when on time or no forecast) |
| Delayed | On when the next train is at least a minute late |
| Number of services in the next hour | Count of non-cancelled trains leaving within the hour. The `services` attribute lists them (scheduled and expected time, delay, platform, operator, destination, cancelled) |

Cancelled trains are skipped when picking the "next" train.

## Installation

### HACS (custom repository)

1. In Home Assistant, open **HACS**, then the three-dot menu, then **Custom repositories**.
2. Add `https://github.com/quantumkid/uk-train-times` with the type **Integration**.
3. Find **UK Train Times** in HACS and select **Download**.
4. Restart Home Assistant.

### Manual

Copy `custom_components/uk_train_times` into the `custom_components` folder of your Home Assistant configuration, then restart.

On first load Home Assistant installs the [`rtt-io-api`](https://github.com/quantumkid/rtt_io_api) library, so it needs internet access.

## Setup

1. Go to **Settings → Devices & services → Add integration** and search for **UK Train Times**.
2. Enter your Realtime Trains API **refresh token**.
3. Select **Add a route to monitor** and fill in:
   - **From station** and **To station**. The train must call at both.
   - **Minimum minutes until departure**: ignore trains leaving sooner than this, for example your walk to the station.
   - **Hours of interest** (collapsed section): only look for trains between these times each day. Defaults to 06:00 to midnight. An end time before the start time covers an overnight period, and the same start and end covers the whole day.

Use **Reconfigure** on the integration to change the API token, or on a route to change its stations, offset or hours. Changing the stations creates a new route, with a new device and entities.

## API rate limits

The Realtime Trains API is limited to 10 requests a minute, 100 an hour, 1,000 a day and 10,000 a week. To stay within that, the integration:

- polls less often the further away the next train is (about half the time until it leaves, between 1 and 30 minutes, longer with several routes)
- makes no requests outside a route's hours of interest. It fetches the first trains of the next period once and reuses them until that period starts
- backs off for as long as the API's `Retry-After` header asks when it is rate limited

One route costs roughly 200 to 600 requests a day, depending on how busy the line is and how many hours you watch. Several routes add up, so use hours of interest to keep within the daily limit.
