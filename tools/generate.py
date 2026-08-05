#!/usr/bin/env python3
"""
Generates the zero-configuration package and dashboard.

    python3 tools/generate.py --zones 6

Everything a user would otherwise edit in YAML lives in helper entities
instead: flow rate, run time, zone on/off, weather entity, weekly schedule.
The only hard requirement is the naming convention switch.irrigation_zone_N,
because integration and utility_meter need a literal source entity at
configuration time - a template is not allowed there.
"""
import argparse, pathlib, sys, textwrap

# Paths are resolved against the repository root, not the current working
# directory, so the script can be called from anywhere.
ROOT = pathlib.Path(__file__).resolve().parent.parent

PALETTE = ["#30D158", "#FF9F0A", "#64D2FF", "#5E5CE6", "#FF375F", "#BF5AF2",
           "#FFD60A", "#40C8E0"]


def package(n: int) -> str:
    Z = range(1, n + 1)
    out = []
    A = out.append

    A(f"""# =============================================================================
#  IRRIGATION - Home Assistant package        {n} zone slots
#  Place at /config/packages/irrigation.yaml
#
#  NOTHING IN THIS FILE NEEDS EDITING.
#  Rename your valve entities to switch.irrigation_zone_1 ... _{n} and set
#  everything else from the dashboard: flow rate, run time, which zones exist,
#  weather entity, weekly schedule.
#
#  Why the naming convention is unavoidable: the integration and utility_meter
#  platforms resolve "source" at configuration time, so the entity id has to be
#  literal. A template is not allowed there. Renaming four entities in the UI is
#  the cheaper end of that trade.
#
#  Need more slots? Regenerate: python3 tools/generate.py --zones 10
# =============================================================================

input_boolean:
  irrigation_enabled:
    name: Irrigation enabled
    icon: mdi:power
  # Set by the blueprints while a cycle runs. Blocks manual starts and needs no
  # automation entity id anywhere, so renaming an automation cannot break it.
  irrigation_running:
    name: Irrigation cycle running
    icon: mdi:robot""")
    for i in Z:
        A(f"""  irrigation_zone_{i}_enabled:
    name: Zone {i} in use
    icon: mdi:valve""")

    A("\ninput_number:")
    for i in Z:
        A(f"""  irrigation_zone_{i}_rate:
    name: Zone {i} flow rate
    icon: mdi:water-pump
    min: 1
    max: 3000
    step: 1
    unit_of_measurement: L/h
    mode: box
  irrigation_zone_{i}_duration:
    name: Zone {i} run time
    icon: mdi:timer-outline
    min: 1
    max: 120
    step: 1
    unit_of_measurement: min
  # Written by the run script and by the blueprint. Only used to work out the
  # remaining time, never shown as a control.
  irrigation_zone_{i}_last_duration:
    name: Zone {i} active run time
    icon: mdi:timer-sand
    min: 0
    max: 240
    step: 1
    unit_of_measurement: min""")

    A(f"""
input_text:
  irrigation_weather:
    name: Weather entity
    icon: mdi:weather-partly-rainy
    max: 255
  # Compact weekly plan for the display card, for example
  #   Mon:1,3|Tue:2,3|Wed:1,3|Thu:3|Fri:1,3|Sat:2,3|Sun:1,3
  # Numbers are zone slots. Presentation only - the real schedule lives in the
  # blueprints and has to match.
  irrigation_schedule:
    name: Weekly plan
    icon: mdi:calendar-week
    max: 255

input_datetime:
  irrigation_counter_start:
    name: Counting since
    icon: mdi:calendar-start
    has_date: true
    has_time: false

# -----------------------------------------------------------------------------
# RIEMANN INTEGRATION  (L/h -> L, counts up, never reset)
# -----------------------------------------------------------------------------
sensor:""")
    for i in Z:
        A(f"""  - platform: integration
    name: Irrigation Zone {i} Total
    unique_id: irrigation_zone_{i}_total
    source: sensor.irrigation_zone_{i}_flow
    method: left
    unit_time: h
    round: 1
    max_sub_interval:
      minutes: 1""")

    A("\n# -----------------------------------------------------------------------------\n"
      "# METERS\n"
      "# -----------------------------------------------------------------------------\nutility_meter:")
    for i in Z:
        for per, cyc in (("today", "daily"), ("week", "weekly"),
                         ("month", "monthly"), ("since", None)):
            A(f"""  irrigation_zone_{i}_{per}:
    name: Irrigation Zone {i} {per.capitalize()}
    source: sensor.irrigation_zone_{i}_total""" + (f"\n    cycle: {cyc}" if cyc else ""))

    A("\n# -----------------------------------------------------------------------------\n"
      "# TEMPLATE SENSORS\n"
      "# -----------------------------------------------------------------------------\ntemplate:\n  - sensor:")

    for i in Z:
        A(f"""      # ---------- Zone {i} ----------
      - name: Irrigation Zone {i} Flow
        unique_id: irrigation_zone_{i}_flow
        unit_of_measurement: L/h
        state_class: measurement
        state: >-
          {{% if is_state('input_boolean.irrigation_zone_{i}_enabled','on')
                and is_state('switch.irrigation_zone_{i}','on') %}}
            {{{{ states('input_number.irrigation_zone_{i}_rate') | float(0) }}}}
          {{% else %}}0{{% endif %}}

      - name: Irrigation Zone {i} Name
        unique_id: irrigation_zone_{i}_name
        state: >-
          {{{{ state_attr('switch.irrigation_zone_{i}','friendly_name') or 'Zone {i}' }}}}

      - name: Irrigation Zone {i} Remaining
        unique_id: irrigation_zone_{i}_remaining
        unit_of_measurement: min
        state: >-
          {{% set s = states.switch.irrigation_zone_{i} %}}
          {{% if s is not none and s.state == 'on' %}}
            {{% set ziel = states('input_number.irrigation_zone_{i}_last_duration') | float(0) %}}
            {{% set lief = (now() - s.last_changed).total_seconds() / 60 %}}
            {{{{ [ziel - lief, 0] | max | round(0) }}}}
          {{% else %}}0{{% endif %}}""")

    def summe(per):
        teile = " ".join(
            f"+ states('sensor.irrigation_zone_{i}_{per}') | float(0)" for i in Z)
        return "{{ ( 0 " + teile + " ) | round(0) }}"

    A("\n      # ---------- Totals ----------")
    for per in ("today", "week", "month", "since"):
        A(f"""      - name: Irrigation Water {per.capitalize()}
        unique_id: irrigation_water_{per}
        unit_of_measurement: L
        state_class: measurement
        icon: mdi:water-outline
        state: >-
          {summe(per)}""")

    aktiv = " or ".join(f"is_state('switch.irrigation_zone_{i}','on')" for i in Z)
    fluss = " ".join(f"+ states('sensor.irrigation_zone_{i}_flow') | float(0)" for i in Z)
    rest = ", ".join(f"states('sensor.irrigation_zone_{i}_remaining') | float(0)" for i in Z)

    A(f"""
      # ---------- Global status ----------
      - name: Irrigation Flow
        unique_id: irrigation_flow
        unit_of_measurement: L/h
        state_class: measurement
        icon: mdi:water-pump
        state: "{{{{ ( 0 {fluss} ) | round(0) }}}}"

      - name: Irrigation Remaining
        unique_id: irrigation_remaining
        unit_of_measurement: min
        state: "{{{{ [ {rest} ] | max | round(0) }}}}"

      - name: Irrigation Active Zones
        unique_id: irrigation_active_zones
        icon: mdi:sprinkler-variant
        state: >-
          {{% set ns = namespace(l=[]) %}}
          {{% for i in range(1, {n + 1}) %}}
            {{% if is_state('switch.irrigation_zone_' ~ i, 'on') %}}
              {{% set ns.l = ns.l + [ states('sensor.irrigation_zone_' ~ i ~ '_name') ] %}}
            {{% endif %}}
          {{% endfor %}}
          {{{{ ns.l | join(' + ') if ns.l else 'Ready' }}}}

      - name: Irrigation Daily Average
        unique_id: irrigation_daily_average
        unit_of_measurement: L
        state: >-
          {{% set tage = now().weekday() %}}
          {{% if tage < 1 %}}unknown{{% else %}}
          {{{{ (( states('sensor.irrigation_water_week') | float(0)
              - states('sensor.irrigation_water_today') | float(0) ) / tage) | round(0) }}}}
          {{% endif %}}

      - name: Irrigation Average Since
        unique_id: irrigation_average_since
        unit_of_measurement: L
        state: >-
          {{% set ts = state_attr('input_datetime.irrigation_counter_start','timestamp') %}}
          {{% if ts is none %}}unknown{{% else %}}
          {{% set tage = [ ((now().timestamp() - ts) / 86400) | round(0) | int, 1 ] | max %}}
          {{{{ (states('sensor.irrigation_water_since') | float(0) / tage) | round(0) }}}}
          {{% endif %}}

      - name: Irrigation Counter Start
        unique_id: irrigation_counter_start_text
        icon: mdi:calendar-start
        state: >-
          {{% set ts = state_attr('input_datetime.irrigation_counter_start','timestamp') %}}
          {{{{ ts | timestamp_custom('%d.%m.%Y', true) if ts else 'not set' }}}}

      - name: Irrigation Next Run
        unique_id: irrigation_next_run
        icon: mdi:clock-outline
        state: >-
          {{% set r0 = states('sensor.irrigation_rain_today') | float(0) %}}
          {{% set r1 = states('sensor.irrigation_rain_tomorrow') | float(0) %}}
          {{% set r2 = states('sensor.irrigation_rain_day_after') | float(0) %}}
          {{% if not is_state('input_boolean.irrigation_enabled','on') %}}
            Irrigation switched off
          {{% elif now().hour < 5 %}}
            {{{{ 'Today 05:00 - rain skip likely, ' ~ (r0 + r1) | round(1) ~ ' mm'
                if (r0 + r1) >= 6 else 'Today 05:00' }}}}
          {{% else %}}
            {{{{ 'Tomorrow 05:00 - rain skip likely, ' ~ (r1 + r2) | round(1) ~ ' mm'
                if (r1 + r2) >= 6 else 'Tomorrow 05:00' }}}}
          {{% endif %}}

  - binary_sensor:
      - name: Irrigation Running
        unique_id: irrigation_is_running
        device_class: running
        state: "{{{{ {aktiv} }}}}"
""")

    # ---------------- run log ----------------
    liste = "\n".join(f"          - switch.irrigation_zone_{i}" for i in Z)
    A(f"""  # ---------------------------------------------------------------------------
  # RUN LOG AND FAULTS
  # ---------------------------------------------------------------------------
  - trigger:
      - trigger: state
        id: run
        entity_id:
{liste}
        from: "on"
        to: "off"
      - trigger: state
        id: offline
        entity_id:
{liste}
        to:
          - unavailable
          - unknown
        for:
          minutes: 1
      - trigger: state
        id: online
        entity_id:
{liste}
        from:
          - unavailable
          - unknown
        to:
          - "on"
          - "off"
        for:
          seconds: 30
      - trigger: event
        id: fault
        event_type: irrigation_fault
    sensor:
      - name: Irrigation Log
        unique_id: irrigation_log
        icon: mdi:history
        state: >-
          {{% if trigger.id == 'fault' %}}{{{{ trigger.event.data.zone }}}} -
          {{{{ trigger.event.data.text }}}}{{% else %}}{{{{
          state_attr(trigger.entity_id,'friendly_name') or trigger.entity_id }}}} -
          {{{{ now() | as_local | as_timestamp | timestamp_custom('%d.%m. %H:%M') }}}}{{% endif %}}
        attributes:
          entries: >-
            {{% set raw = this.attributes.get('entries', []) %}}
            {{% set old = raw if (raw is sequence and raw is not string) else [] %}}
            {{% set now_txt = now() | as_local | as_timestamp
                            | timestamp_custom('%d.%m. %H:%M') %}}
            {{% if trigger.id == 'run' %}}
              {{% set slot = trigger.entity_id.split('_')[-1] %}}
              {{% set rate = states('input_number.irrigation_zone_' ~ slot ~ '_rate') | float(0) %}}
              {{% set sec = (trigger.to_state.last_changed
                          - trigger.from_state.last_changed).total_seconds() %}}
              {{% if sec >= 10 %}}
                {{% set e = {{'kind':'run',
                     'zone': states('sensor.irrigation_zone_' ~ slot ~ '_name'),
                     'slot': slot | int,
                     'start': trigger.from_state.last_changed | as_local
                              | as_timestamp | timestamp_custom('%d.%m. %H:%M'),
                     'sec': sec | round(0) | int,
                     'liters': (sec / 3600 * rate) | round(1),
                     'text': ''}} %}}
                {{{{ ([e] + old)[:25] }}}}
              {{% else %}}{{{{ old }}}}{{% endif %}}
            {{% elif trigger.id in ['offline','online'] %}}
              {{% set slot = trigger.entity_id.split('_')[-1] %}}
              {{% set e = {{'kind': 'fault' if trigger.id == 'offline' else 'info',
                   'zone': states('sensor.irrigation_zone_' ~ slot ~ '_name'),
                   'slot': slot | int, 'start': now_txt, 'sec': 0, 'liters': 0,
                   'text': 'Device unreachable' if trigger.id == 'offline'
                           else 'back online'}} %}}
              {{{{ ([e] + old)[:25] }}}}
            {{% elif trigger.id == 'fault' %}}
              {{% set e = {{'kind':'fault', 'zone': trigger.event.data.zone,
                   'slot': 0, 'start': now_txt, 'sec': 0, 'liters': 0,
                   'text': trigger.event.data.text}} %}}
              {{{{ ([e] + old)[:25] }}}}
            {{% else %}}{{{{ old }}}}{{% endif %}}

  # ---------------------------------------------------------------------------
  # RAIN FORECAST
  # The weather entity comes from an input_text, which only works because
  # weather.get_forecasts is called from an action where targets may be
  # templated.
  # ---------------------------------------------------------------------------
  - trigger:
      - trigger: time_pattern
        minutes: "/15"
      - trigger: homeassistant
        event: start
    condition:
      - condition: template
        value_template: "{{{{ has_value('input_text.irrigation_weather') }}}}"
    action:
      - action: weather.get_forecasts
        target:
          entity_id: "{{{{ states('input_text.irrigation_weather') }}}}"
        data:
          type: daily
        response_variable: fc
    sensor:
      - name: Irrigation Rain Today
        unique_id: irrigation_rain_today
        unit_of_measurement: mm
        state: >-
          {{% set f = (fc.values() | list | first).forecast %}}
          {{{{ (f[0].precipitation | float(0)) | round(1) if f | length > 0 else 0 }}}}
      - name: Irrigation Rain Tomorrow
        unique_id: irrigation_rain_tomorrow
        unit_of_measurement: mm
        state: >-
          {{% set f = (fc.values() | list | first).forecast %}}
          {{{{ (f[1].precipitation | float(0)) | round(1) if f | length > 1 else 0 }}}}
      - name: Irrigation Rain Day After
        unique_id: irrigation_rain_day_after
        unit_of_measurement: mm
        state: >-
          {{% set f = (fc.values() | list | first).forecast %}}
          {{{{ (f[2].precipitation | float(0)) | round(1) if f | length > 2 else 0 }}}}
""")

    # ---------------- scripts ----------------
    A("# -----------------------------------------------------------------------------\n"
      "# SCRIPTS\n"
      "# -----------------------------------------------------------------------------\nscript:")
    for i in Z:
        A(f"""  irrigation_zone_{i}_run:
    alias: Irrigation zone {i} manual run
    icon: mdi:play
    mode: restart
    variables:
      minutes: "{{{{ states('input_number.irrigation_zone_{i}_duration') | int(10) }}}}"
    sequence:
      - if:
          - condition: state
            entity_id: input_boolean.irrigation_running
            state: "on"
        then:
          - event: irrigation_fault
            event_data:
              zone: "{{{{ states('sensor.irrigation_zone_{i}_name') }}}}"
              text: Manual start rejected, a cycle is running
          - stop: Cycle running
      - action: input_number.set_value
        target:
          entity_id: input_number.irrigation_zone_{i}_last_duration
        data:
          value: "{{{{ minutes }}}}"
      - action: switch.turn_on
        target:
          entity_id: switch.irrigation_zone_{i}
      - wait_template: "{{{{ is_state('switch.irrigation_zone_{i}','on') }}}}"
        timeout:
          seconds: 90
        continue_on_timeout: true
      - if:
          - condition: not
            conditions:
              - condition: state
                entity_id: switch.irrigation_zone_{i}
                state: "on"
        then:
          - event: irrigation_fault
            event_data:
              zone: "{{{{ states('sensor.irrigation_zone_{i}_name') }}}}"
              text: Valve did not confirm the start
          - stop: Start not confirmed
      - delay:
          minutes: "{{{{ minutes }}}}"
      - action: switch.turn_off
        target:
          entity_id: switch.irrigation_zone_{i}

  irrigation_zone_{i}_toggle:
    alias: Irrigation zone {i} start/stop
    icon: mdi:play-pause
    mode: restart
    sequence:
      - if:
          - condition: or
            conditions:
              - condition: state
                entity_id: switch.irrigation_zone_{i}
                state: "on"
              - condition: state
                entity_id: script.irrigation_zone_{i}_run
                state: "on"
        then:
          - action: script.turn_off
            target:
              entity_id: script.irrigation_zone_{i}_run
          - action: switch.turn_off
            target:
              entity_id: switch.irrigation_zone_{i}
        else:
          - action: script.turn_on
            target:
              entity_id: script.irrigation_zone_{i}_run
""")

    alle_scripts = "\n".join(f"            - script.irrigation_zone_{i}_run" for i in Z)
    alle_switches = "\n".join(f"            - switch.irrigation_zone_{i}" for i in Z)
    alle_meter = "\n".join(
        f"            - sensor.irrigation_zone_{i}_since" for i in Z)
    A(f"""  irrigation_stop_all:
    alias: Irrigation stop everything
    icon: mdi:stop
    mode: single
    sequence:
      - action: script.turn_off
        target:
          entity_id:
{alle_scripts}
      - action: switch.turn_off
        target:
          entity_id:
{alle_switches}

# -----------------------------------------------------------------------------
# AUTOMATIONS
# -----------------------------------------------------------------------------
automation:
  # Changing the start date resets the "since" meters only. Counting backwards
  # is impossible - the date is a starting mark, not a filter.
  - id: irrigation_counter_start_changed
    alias: Irrigation - counter start changed
    mode: single
    triggers:
      - trigger: state
        entity_id: input_datetime.irrigation_counter_start
        not_from:
          - unknown
          - unavailable
        not_to:
          - unknown
          - unavailable
    conditions:
      - condition: template
        value_template: >-
          {{{{ trigger.from_state is not none and trigger.to_state is not none
             and trigger.from_state.state != trigger.to_state.state }}}}
    actions:
      - action: utility_meter.reset
        target:
          entity_id:
{alle_meter}

  # If a blueprint aborts mid-cycle the running flag would stay on and block
  # every manual start. This clears it after three hours and logs it.
  - id: irrigation_running_flag_watchdog
    alias: Irrigation - clear stuck cycle flag
    mode: single
    triggers:
      - trigger: state
        entity_id: input_boolean.irrigation_running
        to: "on"
        for:
          hours: 3
    actions:
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.irrigation_running
      - event: irrigation_fault
        event_data:
          zone: Cycle
          text: Cycle flag was stuck, cleared automatically

  - id: irrigation_morning_check
    alias: Irrigation - morning cycle check
    mode: single
    triggers:
      - trigger: time
        at: "06:30:00"
    conditions:
      - condition: state
        entity_id: input_boolean.irrigation_enabled
        state: "on"
      - condition: template
        value_template: "{{{{ states('sensor.irrigation_water_today') | float(0) < 0.2 }}}}"
    actions:
      - event: irrigation_fault
        event_data:
          zone: Morning cycle
          text: No water flowed before 06:30
""")
    return "\n".join(out) + "\n"





# =============================================================================
#  DASHBOARD
# =============================================================================
import json


def dashboard(n: int) -> str:
    Z = list(range(1, n + 1))
    farbe = {i: PALETTE[(i - 1) % len(PALETTE)] for i in Z}

    def an(i):
        return (f"{{% set on = is_state('switch.irrigation_zone_{i}','on') "
                f"or is_state('script.irrigation_zone_{i}_run','on') %}}")

    stat_mod = ("ha-card { border: none; border-radius: 22px; }\n"
                "mushroom-state-info $ .primary {\n  font-size: 21px;\n"
                "  font-weight: 600;\n  letter-spacing: -0.02em;\n"
                "  font-variant-numeric: tabular-nums;\n}\n")

    def zone_sichtbar(karte, i):
        return {"type": "conditional",
                "conditions": [{"condition": "state",
                                "entity": f"input_boolean.irrigation_zone_{i}_enabled",
                                "state": "on"}],
                "card": karte,
                "grid_options": karte.pop("grid_options")}

    def info_karte(i):
        return {
            "type": "custom:mushroom-template-card",
            "primary": f"{{{{ states('sensor.irrigation_zone_{i}_name') }}}}",
            "secondary": (
                f"{an(i)}{{% if on %}}Running - {{{{ "
                f"states('sensor.irrigation_zone_{i}_remaining') }}}} min left"
                f"{{% else %}}{{{{ states('sensor.irrigation_zone_{i}_today') "
                f"| float(0) | round(0) }}}} L today - {{{{ "
                f"states('input_number.irrigation_zone_{i}_rate') | int }}}} L/h"
                f"{{% endif %}}"),
            "icon": (f"{{{{ state_attr('switch.irrigation_zone_{i}','icon')"
                     f" or 'mdi:sprinkler-variant' }}}}"),
            "icon_color": f"{an(i)}{{{{ 'green' if on else 'grey' }}}}",
            "tap_action": {"action": "navigate",
                           "navigation_path": f"#zone-{i}"},
            "hold_action": {"action": "none"},
            "double_tap_action": {"action": "none"},
            "card_mod": {"style": ("ha-card {\n  border: none;\n  box-shadow: none;\n"
                                   "  border-radius: 22px 6px 6px 22px;\n}\n"
                                   "mushroom-state-info $ .primary {\n"
                                   "  font-weight: 600;\n  letter-spacing: -0.01em;\n}\n")},
            "grid_options": {"columns": 7, "rows": 1},
        }

    def start_karte(i, radius, cols=5):
        return {
            "type": "custom:mushroom-template-card",
            "primary": (f"{an(i)}{{% if is_state('input_boolean.irrigation_running','on') "
                        f"%}}Locked{{% elif on %}}Stop{{% else %}}Start{{% endif %}}"),
            "secondary": (f"{an(i)}{{% if is_state('input_boolean.irrigation_running','on') "
                          f"%}}cycle running{{% elif on %}}{{{{ "
                          f"states('sensor.irrigation_zone_{i}_remaining') }}}} min left"
                          f"{{% else %}}{{{{ states('input_number.irrigation_zone_{i}_duration')"
                          f" | int }}}} min{{% endif %}}"),
            "icon": (f"{an(i)}{{% if on %}}mdi:stop-circle-outline"
                     f"{{% else %}}mdi:play-circle-outline{{% endif %}}"),
            "icon_color": (f"{an(i)}{{% if on %}}red{{% elif "
                           f"is_state('input_boolean.irrigation_running','on') %}}disabled"
                           f"{{% else %}}blue{{% endif %}}"),
            "tap_action": {"action": "perform-action",
                           "perform_action": f"script.irrigation_zone_{i}_toggle"},
            "hold_action": {"action": "none"},
            "double_tap_action": {"action": "none"},
            "card_mod": {"style": f"ha-card {{\n  border: none;\n  box-shadow: none;\n"
                                  f"  border-radius: {radius};\n}}\n"},
            "grid_options": {"columns": cols, "rows": 1},
        }

    def popup(i):
        def stat(quelle, label, col):
            return {"type": "custom:mushroom-template-card",
                    "primary": f"{{{{ states('sensor.irrigation_zone_{i}_{quelle}')"
                               f" | float(0) | round(0) }}}} L",
                    "secondary": label, "icon": "mdi:water", "icon_color": col,
                    "tap_action": {"action": "none"},
                    "card_mod": {"style": "ha-card { border: none; border-radius: 18px; }\n"}}
        return {
            "type": "custom:bubble-card",
            "card_type": "pop-up",
            "hash": f"#zone-{i}",
            "name": f"{{{{ states('sensor.irrigation_zone_{i}_name') }}}}",
            "icon": "mdi:sprinkler-variant",
            "bg_blur": 12, "bg_opacity": 88, "shadow_opacity": 40,
            "close_by_clicking_outside": True,
            "cards": [
                {"type": "custom:mushroom-template-card",
                 "primary": (f"{{% set e = state_attr('sensor.irrigation_log','entries') or [] %}}"
                             f"{{% set z = e | selectattr('slot','eq',{i}) | list %}}"
                             f"{{% if z %}}{{{{ z[0].start }}}} - {{{{ z[0].liters }}}} L"
                             f"{{% else %}}no run recorded yet{{% endif %}}"),
                 "secondary": "Last run", "icon": "mdi:history", "icon_color": "grey",
                 "tap_action": {"action": "none"},
                 "card_mod": {"style": "ha-card { border: none; border-radius: 20px; }\n"}},
                {"type": "custom:mushroom-number-card",
                 "entity": f"input_number.irrigation_zone_{i}_duration",
                 "name": "Run time", "icon": "mdi:timer-sand", "icon_color": "grey",
                 "display_mode": "slider",
                 "card_mod": {"style": "ha-card { border: none; border-radius: 20px; }\n"}},
                start_karte(i, "20px", 12),
                {"type": "grid", "columns": 3, "square": False,
                 "cards": [stat("today", "Today", "blue"),
                           stat("week", "Week", "cyan"),
                           stat("month", "Month", "teal")]},
                {"type": "entities", "show_header_toggle": False,
                 "entities": [
                     {"entity": f"input_boolean.irrigation_zone_{i}_enabled",
                      "name": "Zone in use"},
                     {"entity": f"input_number.irrigation_zone_{i}_rate",
                      "name": "Flow rate"},
                     {"entity": f"switch.irrigation_zone_{i}",
                      "name": "Valve, tap to rename"}],
                 "card_mod": {"style": "ha-card { border: none; border-radius: 20px; }\n"}},
                {"type": "history-graph", "hours_to_show": 24, "title": "Last 24 hours",
                 "entities": [{"entity": f"switch.irrigation_zone_{i}"}]},
            ],
        }

    # ---------------- hero ----------------
    hero_js = """[[[
  const N = __N__;
  const zonen = [];
  for (let i = 1; i <= N; i++) {
    const s = states['switch.irrigation_zone_' + i];
    if (s && s.state === 'on') zonen.push(i);
  }
  const on = zonen.length > 0;

  let rest = 0, ziel = 1, laeuft = 0;
  zonen.forEach(i => {
    const r = parseFloat(states['sensor.irrigation_zone_' + i + '_remaining'].state) || 0;
    if (r >= rest) {
      rest = r;
      ziel = Math.max(1, parseFloat(
        states['input_number.irrigation_zone_' + i + '_last_duration'].state) || 1);
    }
    const el = (Date.now() -
      new Date(states['switch.irrigation_zone_' + i].last_changed).getTime()) / 1000;
    if (el > laeuft) laeuft = el;
  });

  const pct   = on ? Math.min(100, Math.max(0, (1 - rest / ziel) * 100)) : 0;
  const flow  = Math.round(parseFloat(states['sensor.irrigation_flow'].state) || 0);
  const today = Math.round(parseFloat(states['sensor.irrigation_water_today'].state) || 0);

  const kicker = on ? states['sensor.irrigation_active_zones'].state : 'Used today';
  const big    = on ? Math.ceil(rest) : today;
  const unit   = on ? 'min' : 'L';
  const sub    = on ? flow + ' L/h - target ' + Math.round(ziel) + ' min'
                    : states['sensor.irrigation_next_run'].state;

  // SMIL rather than CSS keyframes. A negative begin resumes the wave at the
  // right phase whenever the card is re-rendered.
  const welle = (y, amp, dur, fill) => {
    const start = -(laeuft % dur).toFixed(2);
    const p = `M0,${y} C 100,${y-amp} 300,${y+amp} 400,${y}`
            + ` C 500,${y-amp} 700,${y+amp} 800,${y}`
            + ` C 900,${y-amp} 1100,${y+amp} 1200,${y} L1200,120 L0,120 Z`;
    return `<svg viewBox="0 0 800 120" preserveAspectRatio="none"
                 style="position:absolute;inset:0;width:100%;height:100%;">
              <g><animateTransform attributeName="transform" type="translate"
                   from="0 0" to="-400 0" dur="${dur}s" begin="${start}s"
                   repeatCount="indefinite"/>
                 <path d="${p}" fill="${fill}"/></g></svg>`;
  };

  const wasser = on ? `
    <div style="position:absolute;inset:0;background:linear-gradient(180deg,
                rgba(10,132,255,.10),rgba(100,210,255,.20));"></div>
    <div style="position:absolute;left:0;right:0;bottom:0;height:78%;overflow:hidden;">
      ${welle(60, 15, 9, 'rgba(140,205,255,0.22)')}
      ${welle(78, 11, 6.5, 'rgba(255,255,255,0.10)')}
    </div>
    <div style="position:absolute;left:0;bottom:0;height:4px;width:${pct}%;
                background:rgba(255,255,255,.6);border-radius:0 4px 4px 0;
                transition:width 1200ms cubic-bezier(.32,.72,0,1);"></div>` : '';

  return `
    <div style="position:relative;overflow:hidden;height:100%;display:flex;
                flex-direction:column;justify-content:center;">
      ${wasser}
      <div style="position:relative;padding:20px 24px;text-align:left;">
        <div style="font-size:12px;font-weight:600;letter-spacing:.08em;
                    text-transform:uppercase;opacity:.55;">${kicker}</div>
        <div style="display:flex;align-items:baseline;gap:8px;margin-top:4px;">
          <span style="font-size:56px;font-weight:600;line-height:1;
                       letter-spacing:-.04em;font-variant-numeric:tabular-nums;">${big}</span>
          <span style="font-size:21px;font-weight:500;opacity:.5;">${unit}</span>
        </div>
        <div style="margin-top:8px;font-size:14px;opacity:.6;">${sub}</div>
      </div>
    </div>`;
]]]""".replace("__N__", str(n))

    plan_js = """[[[
  // Reads input_text.irrigation_schedule, format
  //   Mon:1,3|Tue:2,3|Wed:1,3|Thu:3|Fri:1,3|Sat:2,3|Sun:1,3
  const PAL = __PAL__;
  const raw = (states['input_text.irrigation_schedule'] || {}).state || '';
  const tage = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const plan = {};
  raw.split('|').forEach(t => {
    const [tag, rest] = t.split(':');
    if (!tag) return;
    plan[tag.trim()] = (rest || '').split(',')
      .map(s => parseInt(s, 10)).filter(v => v > 0);
  });

  if (!Object.keys(plan).length) return `
    <div style="padding:18px;font-size:13px;opacity:.45;line-height:1.6;">
      No schedule set.<br>
      Fill input_text.irrigation_schedule, for example<br>
      <code>Mon:1,3|Tue:2,3|Wed:1,3|Thu:3|Fri:1,3|Sat:2,3|Sun:1,3</code>
    </div>`;

  const heute = (new Date().getDay() + 6) % 7;
  const genutzt = [...new Set(Object.values(plan).flat())].sort((a,b) => a-b);

  const spalten = tage.map((tag, i) => {
    const aktiv = i === heute;
    const slots = plan[tag] || [];
    const punkte = genutzt.map(z => {
      const an = slots.includes(z);
      return `<div style="width:8px;height:8px;border-radius:50%;margin:0 auto;
                background:${an ? PAL[(z-1) % PAL.length] : 'currentColor'};
                opacity:${an ? 1 : .12};"></div>`;
    }).join('<div style="height:7px"></div>');
    return `<div style="flex:1;text-align:center;padding:12px 0 14px;border-radius:14px;
                 background:${aktiv ? 'rgba(10,132,255,.14)' : 'transparent'};">
              <div style="font-size:12px;font-weight:${aktiv ? 700 : 500};
                          letter-spacing:.04em;opacity:${aktiv ? 1 : .45};
                          margin-bottom:10px;">${tag}</div>${punkte}</div>`;
  }).join('');

  const legende = genutzt.map(z => {
    const s = states['sensor.irrigation_zone_' + z + '_name'];
    const name = s ? s.state : 'Zone ' + z;
    return `<span style="display:inline-flex;align-items:center;gap:6px;
                   font-size:12px;opacity:.6;margin-right:16px;">
              <span style="width:7px;height:7px;border-radius:50%;
                    background:${PAL[(z-1) % PAL.length]};"></span>${name}</span>`;
  }).join('');

  return `<div style="padding:16px 12px 14px;box-sizing:border-box;">
            <div style="display:flex;gap:2px;">${spalten}</div>
            <div style="margin-top:14px;padding-top:14px;
                        border-top:1px solid rgba(127,127,127,.16);
                        display:flex;flex-wrap:wrap;align-items:center;">${legende}</div>
          </div>`;
]]]""".replace("__PAL__", json.dumps([PALETTE[(i - 1) % len(PALETTE)] for i in Z]))

    log_js = """[[[
  const PAL = __PAL__;
  const WARN = '#FF453A', INFO = '#8E8E93';
  const a = states['sensor.irrigation_log']
          ? states['sensor.irrigation_log'].attributes.entries : null;
  const e = Array.isArray(a) ? a : [];

  if (!e.length) return `
    <div style="padding:18px;font-size:13px;opacity:.45;line-height:1.6;">
      No entries yet.<br>The list starts with the next run or the next fault.
    </div>`;

  const dauer = s => {
    const v = Number(s);
    if (!isFinite(v) || v <= 0) return '';
    return v < 60 ? `${Math.round(v)} s` : `${Math.round(v / 60)} min`;
  };

  const zeilen = e.map(x => {
    const warn = x.kind === 'fault', info = x.kind === 'info';
    const col = warn ? WARN : info ? INFO : PAL[((x.slot || 1) - 1) % PAL.length];
    const right = (warn || info)
      ? `<span style="display:block;font-size:12px;opacity:.6;max-width:150px;">
           ${x.text || ''}</span>`
      : `<span style="display:block;font-size:14px;font-weight:600;
                      font-variant-numeric:tabular-nums;">${x.liters ?? 0} L</span>
         <span style="display:block;font-size:12px;opacity:.5;">${dauer(x.sec)}</span>`;
    return `<div style="display:flex;align-items:center;gap:12px;padding:11px 14px;
                 border-bottom:1px solid rgba(127,127,127,.10);box-sizing:border-box;
                 background:${warn ? 'rgba(255,69,58,.07)' : 'transparent'};">
              <span style="width:8px;height:8px;border-radius:50%;flex:none;
                    background:${col};"></span>
              <span style="flex:1;min-width:0;">
                <span style="display:block;font-size:14px;font-weight:600;
                      letter-spacing:-.01em;color:${warn ? WARN : 'inherit'};">
                  ${x.zone || 'Irrigation'}</span>
                <span style="display:block;font-size:12px;opacity:.5;">
                  ${x.start || ''}</span></span>
              <span style="text-align:right;flex:none;">${right}</span>
            </div>`;
  }).join('');

  return `<div style="max-height:238px;overflow-y:auto;overscroll-behavior:contain;
                      touch-action:pan-y;-webkit-overflow-scrolling:touch;">
            ${zeilen}</div>`;
]]]""".replace("__PAL__", json.dumps([PALETTE[(i - 1) % len(PALETTE)] for i in Z]))

    serien = [{"entity": f"sensor.irrigation_zone_{i}_total", "name": f"Zone {i}",
               "type": "column", "color": farbe[i], "unit": " L",
               "group_by": {"func": "diff", "duration": "1d"}} for i in Z]
    donut_serien = [{"entity": f"sensor.irrigation_zone_{i}_month",
                     "name": f"Zone {i}", "color": farbe[i]} for i in Z]

    H = lambda t, ic, st="title": {"type": "heading", "heading": t,
                                   "heading_style": st, "icon": ic}

    s1 = [
        {"type": "custom:mushroom-chips-card", "alignment": "start",
         "chips": [
             {"type": "entity", "entity": "input_boolean.irrigation_enabled",
              "icon": "mdi:power", "content_info": "none",
              "tap_action": {"action": "toggle"}},
             {"type": "template", "icon": "mdi:water-percent",
              "content": "{{ states('sensor.irrigation_water_week') }} L / week"},
             {"type": "template", "icon": "mdi:weather-rainy",
              "content": "{{ states('sensor.irrigation_rain_tomorrow') }} mm tomorrow"},
             {"type": "template", "icon": "mdi:robot-outline",
              "content": ("{{ 'Cycle running' if "
                          "is_state('input_boolean.irrigation_running','on') else 'Ready' }}")}],
         "card_mod": {"style": "ha-card { --chip-background: rgba(127,127,127,0.10);"
                               " --chip-border-width: 0; }\n"},
         "grid_options": {"columns": 12, "rows": 1}},
        {"type": "custom:button-card", "entity": "binary_sensor.irrigation_running",
         "show_icon": False, "show_name": False, "show_state": False, "show_label": False,
         "tap_action": {"action": "none"},
         "triggers_update": ["sensor.irrigation_remaining", "sensor.irrigation_active_zones",
                             "sensor.irrigation_next_run", "sensor.irrigation_water_today",
                             "sensor.irrigation_flow"],
         "grid_options": {"columns": 12, "rows": 3},
         "styles": {"grid": [{"grid-template-areas": '"hero"'},
                             {"grid-template-columns": "1fr"}],
                    "card": [{"padding": 0}, {"border": "none"},
                             {"border-radius": "28px"}, {"overflow": "hidden"},
                             {"height": "100%"},
                             {"box-shadow": "0 10px 30px rgba(0,0,0,0.16)"}],
                    "custom_fields": {"hero": [{"width": "100%"}, {"height": "100%"},
                                               {"white-space": "normal"}]}},
         "custom_fields": {"hero": hero_js}},
        {"type": "conditional",
         "conditions": [{"condition": "state", "entity": "binary_sensor.irrigation_running",
                         "state": "on"}],
         "card": {"type": "custom:mushroom-template-card", "primary": "Stop everything",
                  "secondary": "Ends every running zone immediately",
                  "icon": "mdi:stop-circle-outline", "icon_color": "red",
                  "fill_container": True,
                  "tap_action": {"action": "perform-action",
                                 "perform_action": "script.irrigation_stop_all"},
                  "card_mod": {"style": "ha-card {\n  border: none;\n"
                                        "  border-radius: 24px;\n"
                                        "  background: rgba(255,69,58,0.10);\n}\n"}},
         "grid_options": {"columns": 12, "rows": "auto"}},
        H("Weekly plan", "mdi:calendar-week"),
        {"type": "custom:button-card", "entity": "input_text.irrigation_schedule",
         "show_icon": False, "show_name": False, "show_state": False,
         "tap_action": {"action": "none"},
         "grid_options": {"columns": 12, "rows": 3},
         "styles": {"grid": [{"grid-template-areas": '"plan"'},
                             {"grid-template-columns": "1fr"}],
                    "card": [{"padding": 0}, {"border": "none"},
                             {"border-radius": "28px"}, {"box-shadow": "none"}],
                    "custom_fields": {"plan": [{"width": "100%"},
                                               {"white-space": "normal"}]}},
         "custom_fields": {"plan": plan_js}},
        {"type": "custom:mushroom-template-card",
         "primary": "{{ states('sensor.irrigation_next_run') }}",
         "secondary": "Next scheduled run", "icon": "mdi:clock-time-five-outline",
         "icon_color": "blue", "multiline_secondary": True,
         "tap_action": {"action": "none"},
         "card_mod": {"style": "ha-card { border: none; border-radius: 24px; }\n"
                               "mushroom-state-info $ .primary { font-weight: 600; }\n"},
         "grid_options": {"columns": 12, "rows": "auto"}},
        H("Recent activity", "mdi:history"),
        {"type": "custom:button-card", "entity": "sensor.irrigation_log",
         "show_icon": False, "show_name": False, "show_state": False,
         "tap_action": {"action": "none"}, "hold_action": {"action": "none"},
         "styles": {"grid": [{"grid-template-areas": '"list"'},
                             {"grid-template-columns": "1fr"}],
                    "card": [{"padding": 0}, {"border": "none"},
                             {"border-radius": "28px"}, {"box-shadow": "none"},
                             {"overflow": "hidden"}, {"pointer-events": "none"}],
                    "custom_fields": {"list": [{"width": "100%"},
                                               {"white-space": "normal"},
                                               {"pointer-events": "auto"}]}},
         "custom_fields": {"list": log_js},
         "grid_options": {"columns": 12, "rows": 4}},
    ]

    s2 = [
        H("Consumption", "mdi:chart-box-outline"),
        {"type": "custom:apexcharts-card",
         "header": {"show": True, "title": "Daily use, 7 days", "show_states": False},
         "graph_span": "7d", "span": {"end": "day"}, "stacked": True,
         "update_interval": "30s",
         "apex_config": {"chart": {"height": 240, "toolbar": {"show": False}},
                         "plotOptions": {"bar": {"columnWidth": "26px", "borderRadius": 3}},
                         "grid": {"borderColor": "rgba(127,127,127,0.12)",
                                  "strokeDashArray": 0},
                         "legend": {"position": "bottom", "markers": {"radius": 6}},
                         "dataLabels": {"enabled": False},
                         "xaxis": {"axisBorder": {"show": False},
                                   "axisTicks": {"show": False},
                                   "tooltip": {"enabled": False}},
                         "tooltip": {"shared": True}},
         "series": serien,
         "card_mod": {"style": "ha-card { border: none; border-radius: 28px; }\n"},
         "grid_options": {"columns": 12, "rows": "auto"}},
        {"type": "custom:apexcharts-card", "chart_type": "donut",
         "header": {"show": True, "title": "Share this month", "show_states": False},
         "apex_config": {"chart": {"height": 240}, "legend": {"position": "bottom"},
                         "plotOptions": {"pie": {"donut": {
                             "size": "74%",
                             "labels": {"show": True,
                                        "name": {"show": True, "fontSize": "13px",
                                                 "color": "var(--primary-text-color)",
                                                 "offsetY": 22},
                                        "value": {"show": True, "fontSize": "28px",
                                                  "fontWeight": 600,
                                                  "color": "var(--primary-text-color)",
                                                  "offsetY": -16,
                                                  "formatter": "EVAL:function(v) {\n"
                                                               "  return Number(v).toFixed(0) + ' L';\n}"},
                                        "total": {"show": True, "showAlways": True,
                                                  "label": "Total", "fontSize": "13px",
                                                  "color": "var(--primary-text-color)",
                                                  "formatter": "EVAL:function(w) {\n"
                                                               "  const s = w.globals.seriesTotals"
                                                               ".reduce((a,b) => a+b, 0);\n"
                                                               "  return s.toFixed(0) + ' L';\n}"}}}}},
                         "stroke": {"width": 0}, "dataLabels": {"enabled": False}},
         "series": donut_serien,
         "card_mod": {"style": "ha-card { border: none; border-radius: 28px; }\n"},
         "grid_options": {"columns": 12, "rows": "auto"}},
        {"type": "custom:mushroom-template-card",
         "primary": "{{ states('sensor.irrigation_water_today') }} L",
         "secondary": ("{% set a = states('sensor.irrigation_daily_average') %}"
                       "{% if a in ['unknown','unavailable'] %}Today"
                       "{% else %}Today - avg {{ a }} L{% endif %}"),
         "icon": "mdi:weather-sunny",
         "icon_color": ("{% set a = states('sensor.irrigation_daily_average') | float(0) %}"
                        "{% set h = states('sensor.irrigation_water_today') | float(0) %}"
                        "{% if a > 0 and h > a * 2 %}orange{% else %}blue{% endif %}"),
         "multiline_secondary": True, "tap_action": {"action": "none"},
         "card_mod": {"style": stat_mod}, "grid_options": {"columns": 6, "rows": "auto"}},
        {"type": "custom:mushroom-template-card",
         "primary": "{{ states('sensor.irrigation_water_since') }} L",
         "secondary": ("since {{ states('sensor.irrigation_counter_start') }} - "
                       "avg {{ states('sensor.irrigation_average_since') }} L/day"),
         "icon": "mdi:counter", "icon_color": "indigo",
         "entity": "input_datetime.irrigation_counter_start",
         "multiline_secondary": True, "tap_action": {"action": "more-info"},
         "card_mod": {"style": stat_mod}, "grid_options": {"columns": 6, "rows": "auto"}},
    ]

    s3 = [H("Zones", "mdi:valve")]
    for i in Z:
        s3.append(zone_sichtbar(info_karte(i), i))
        s3.append(zone_sichtbar(start_karte(i, "6px 22px 22px 6px"), i))
    s3 += [
        H("Setup", "mdi:tune", "subtitle"),
        {"type": "entities", "show_header_toggle": False,
         "entities": [
             {"entity": "input_boolean.irrigation_enabled", "name": "Irrigation enabled"},
             {"entity": "input_text.irrigation_weather", "name": "Weather entity"},
             {"entity": "input_text.irrigation_schedule", "name": "Weekly plan"},
             {"type": "divider"},
             {"entity": "input_datetime.irrigation_counter_start", "name": "Counting since"},
             {"entity": "sensor.irrigation_water_since", "name": "Total since start"}],
         "card_mod": {"style": "ha-card { border: none; border-radius: 24px; }\n"},
         "grid_options": {"columns": 12, "rows": "auto"}},
    ] + [popup(i) for i in Z]

    view = {"views": [{"title": "Irrigation", "path": "irrigation",
                       "icon": "mdi:sprinkler-variant", "type": "sections",
                       "max_columns": 3, "dense_section_placement": True,
                       "header": {"badges_position": "bottom", "layout": "start"},
                       "sections": [{"type": "grid", "cards": s1},
                                    {"type": "grid", "cards": s2},
                                    {"type": "grid", "cards": s3}]}]}

    import yaml as _y

    class D(_y.SafeDumper):
        def ignore_aliases(self, data): return True

    def rep(dumper, data):
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)
    D.add_representer(str, rep)

    kopf = f"""# =============================================================================
#  IRRIGATION - Lovelace dashboard        {n} zone slots
#  Paste into the raw configuration editor of a new dashboard.
#
#  Nothing in this file needs editing. Zones that are switched off in
#  input_boolean.irrigation_zone_N_enabled are hidden automatically.
#  Zone names come from the friendly name of the valve entity, so renaming a
#  zone is done in the more-info dialog inside the zone pop-up.
#
#  Chart legends use slot numbers rather than names, because apexcharts-card
#  resolves series names at configuration time and cannot template them.
# =============================================================================

"""
    return kopf + _y.dump(view, Dumper=D, sort_keys=False, allow_unicode=True,
                          width=100, indent=2, default_flow_style=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Generate the irrigation package and dashboard")
    ap.add_argument("--zones", type=int, default=6,
                    help="number of zone slots (default 6)")
    ap.add_argument("--package", default=str(ROOT / "packages" / "irrigation.yaml"),
                    help="output path for the package")
    ap.add_argument("--dashboard", default=str(ROOT / "dashboard" / "irrigation.yaml"),
                    help="output path for the dashboard")
    a = ap.parse_args()

    try:
        import yaml  # noqa: F401
    except ImportError:
        raise SystemExit("PyYAML is missing:  pip install pyyaml")

    if a.zones < 1 or a.zones > len(PALETTE):
        raise SystemExit(f"--zones must be between 1 and {len(PALETTE)}. "
                         "For more, extend PALETTE at the top of this file.")

    for pfad, inhalt in ((a.package, package(a.zones)),
                         (a.dashboard, dashboard(a.zones))):
        p = pathlib.Path(pfad)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inhalt, encoding="utf-8")
        print(f"{p}: {a.zones} zone slots, "
              f"{len(inhalt.splitlines())} lines")
