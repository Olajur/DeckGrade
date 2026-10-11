import {
  ButtonItem,
  Field,
  PanelSection,
  PanelSectionRow,
  SliderField,
  ToggleField,
  staticClasses,
  useQuickAccessVisible,
} from "@decky/ui";
import { addEventListener, callable, definePlugin, removeEventListener } from "@decky/api";
import { useEffect, useState } from "react";
import { FaSlidersH } from "react-icons/fa";

interface Profile {
  saturation: number;
  contrast: number;
  shadows: number;
  highlights: number;
  vibrance: number;
}

type ProfileKey = keyof Profile;

interface DeckGradeState {
  enabled: boolean;
  global: Profile;
  games: Record<string, Profile>;
  app: string | null;
  active_profile: "global" | "game";
  gamescope: boolean;
  display: string | null;
  xprop: boolean;
}

type Target = "global" | "current";

const STATE_CHANGED = "deckgrade_state_changed";

const getState = callable<[], DeckGradeState>("get_state");
const setEnabled = callable<[enabled: boolean], void>("set_enabled");
const setValue = callable<[target: string, key: string, value: number], void>("set_value");
const resetProfile = callable<[target: string], void>("reset_profile");
const copyGlobalTo = callable<[target: string], void>("copy_global_to");

const noticeStyle = { fontSize: "12px", opacity: 0.7 };

const SLIDERS: {
  key: ProfileKey;
  label: string;
  description: string;
  min: number;
  max: number;
  resetValue?: number;
}[] = [
  {
    key: "saturation",
    label: "Saturation",
    description: "Boosts or reduces color intensity. 100% is neutral, 0% is grayscale.",
    min: 0,
    max: 200,
  },
  {
    key: "contrast",
    label: "Contrast",
    description: "Raises or lowers contrast around the midtones. 100% is neutral.",
    min: 0,
    max: 200,
  },
  {
    key: "shadows",
    label: "Shadows",
    description: "Brightens (+) or deepens (-) dark areas, with little effect on bright ones.",
    min: -100,
    max: 100,
    resetValue: 0,
  },
  {
    key: "highlights",
    label: "Highlights",
    description: "Brightens (+) or tames (-) bright areas, with little effect on dark ones.",
    min: -100,
    max: 100,
    resetValue: 0,
  },
  {
    key: "vibrance",
    label: "Vibrance",
    description: "Native gamescope color vibrance (same engine as the SteamOS Color Vibrance setting).",
    min: 0,
    max: 100,
  },
];

function targetProfile(state: DeckGradeState, target: Target): Profile {
  if (target === "current" && state.app && state.games[state.app]) {
    return state.games[state.app];
  }
  return state.global;
}

function targetFromActive(active: "global" | "game", app: string | null): Target {
  return active === "game" && app ? "current" : "global";
}

function Content() {
  const [state, setState] = useState<DeckGradeState | null>(null);
  const [target, setTarget] = useState<Target>("global");
  const quickAccessVisible = useQuickAccessVisible();

  const applyRefresh = (next: DeckGradeState) => {
    setState(next);
    setTarget(targetFromActive(next.active_profile, next.app));
  };

  const refresh = () => {
    getState()
      .then(applyRefresh)
      .catch((e) => console.error("DeckGrade: refresh failed", e));
  };

  useEffect(() => {
    if (quickAccessVisible) {
      refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quickAccessVisible]);

  useEffect(() => {
    const listener = (next: DeckGradeState) => {
      applyRefresh(next);
    };
    addEventListener(STATE_CHANGED, listener);
    return () => {
      removeEventListener(STATE_CHANGED, listener);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!state) {
    return (
      <PanelSection title="DeckGrade">
        <PanelSectionRow>
          <Field>Loading...</Field>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const controlsDisabled = !state.xprop;
  const profile = targetProfile(state, target);
  const appName = state.app;

  const changeValue = (key: ProfileKey, value: number) => {
    setState((prev) => {
      if (!prev) return prev;
      if (target === "global") {
        return { ...prev, global: { ...prev.global, [key]: value } };
      }
      if (!prev.app) return prev;
      const games = { ...prev.games, [prev.app]: { ...targetProfile(prev, "current"), [key]: value } };
      return { ...prev, games };
    });
    setValue(target, key, value).catch((e) => {
      console.error("DeckGrade: set_value failed", e);
      refresh();
    });
  };

  const doReset = () => {
    resetProfile(target)
      .then(refresh)
      .catch((e) => {
        console.error("DeckGrade: reset_profile failed", e);
        refresh();
      });
  };

  const doCopyGlobal = () => {
    copyGlobalTo("current")
      .then(refresh)
      .catch((e) => {
        console.error("DeckGrade: copy_global_to failed", e);
        refresh();
      });
  };

  return (
    <div>
      <PanelSection title="DeckGrade">
        <PanelSectionRow>
          <ToggleField
            label="Enable display tuning"
            description="Applies the active profile below to the built-in display. Turning this off restores defaults."
            checked={state.enabled}
            disabled={!state.xprop}
            onChange={(enabled) => {
              setState((prev) => (prev ? { ...prev, enabled } : prev));
              setEnabled(enabled);
            }}
          />
        </PanelSectionRow>
        {!state.xprop && (
          <PanelSectionRow>
            <Field>
              <div style={noticeStyle}>
                xprop was not found on this system, display controls are unavailable.
              </div>
            </Field>
          </PanelSectionRow>
        )}
        {state.xprop && !state.gamescope && (
          <PanelSectionRow>
            <Field>
              <div style={noticeStyle}>
                gamescope not detected right now. Settings are saved and applied as soon as it is
                (Game Mode). Check the plugin log if this persists in Game Mode.
              </div>
            </Field>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <Field label="Now playing">
            {appName
              ? `App ${appName} — active profile: ${
                  state.active_profile === "game" ? "per-game" : "global (fallback)"
                }`
              : "None — the global profile is active."}
          </Field>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Color">
        <PanelSectionRow>
          <Field label="Editing">
            {target === "global" ? "Global (fallback) profile" : `Game ${appName} profile`}
          </Field>
        </PanelSectionRow>
        {appName &&
          (target === "global" ? (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={controlsDisabled} onClick={() => setTarget("current")}>
                Switch to game profile
              </ButtonItem>
            </PanelSectionRow>
          ) : (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={controlsDisabled} onClick={() => setTarget("global")}>
                Switch to global profile
              </ButtonItem>
            </PanelSectionRow>
          ))}
        {SLIDERS.map((s) => (
          <PanelSectionRow key={s.key}>
            <SliderField
              label={s.label}
              description={s.description}
              value={profile[s.key]}
              min={s.min}
              max={s.max}
              step={1}
              showValue={true}
              valueSuffix="%"
              resetValue={s.resetValue}
              disabled={controlsDisabled}
              onChange={(value) => changeValue(s.key, value)}
            />
          </PanelSectionRow>
        ))}
      </PanelSection>

      <PanelSection title="Actions">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={controlsDisabled}
            description={
              target === "global"
                ? "Sets the global profile to neutral values and re-enables tuning."
                : `Sets the game ${appName} profile to neutral values.`
            }
            onClick={doReset}
          >
            Reset {target === "global" ? "global" : "game"} profile to defaults
          </ButtonItem>
        </PanelSectionRow>
        {target === "current" && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={controlsDisabled}
              description="Overwrites the game profile with the global profile's current values."
              onClick={doCopyGlobal}
            >
              Reset game profile to global
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>
    </div>
  );
}

export default definePlugin(() => {
  console.log("DeckGrade frontend initializing");

  return {
    name: "DeckGrade",
    titleView: <div className={staticClasses.Title}>DeckGrade</div>,
    content: <Content />,
    icon: <FaSlidersH />,
    onDismount() {
      console.log("DeckGrade frontend unloading");
    },
  };
});
