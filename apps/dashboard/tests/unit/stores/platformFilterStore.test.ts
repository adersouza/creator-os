import { describe, it, expect, beforeEach } from "vitest";
import { usePlatformFilterStore } from "@/src/stores/usePlatformFilterStore";

describe("platformFilterStore", () => {
  beforeEach(() => {
    usePlatformFilterStore.setState({ platform: "all" });
  });

  it("defaults to 'all'", () => {
    expect(usePlatformFilterStore.getState().platform).toBe("all");
  });

  it("setPlatform sets to threads", () => {
    usePlatformFilterStore.getState().setPlatform("threads");
    expect(usePlatformFilterStore.getState().platform).toBe("threads");
  });

  it("setPlatform sets to instagram", () => {
    usePlatformFilterStore.getState().setPlatform("instagram");
    expect(usePlatformFilterStore.getState().platform).toBe("instagram");
  });

  it("setPlatform sets back to all", () => {
    usePlatformFilterStore.getState().setPlatform("threads");
    usePlatformFilterStore.getState().setPlatform("all");
    expect(usePlatformFilterStore.getState().platform).toBe("all");
  });

  it("multiple rapid changes settle on last value", () => {
    usePlatformFilterStore.getState().setPlatform("threads");
    usePlatformFilterStore.getState().setPlatform("instagram");
    usePlatformFilterStore.getState().setPlatform("all");
    usePlatformFilterStore.getState().setPlatform("threads");
    expect(usePlatformFilterStore.getState().platform).toBe("threads");
  });

  it("state changes are independent of other state", () => {
    usePlatformFilterStore.getState().setPlatform("instagram");
    const state = usePlatformFilterStore.getState();
    expect(state.platform).toBe("instagram");
    expect(typeof state.setPlatform).toBe("function");
  });
});
