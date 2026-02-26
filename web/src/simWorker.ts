/// <reference lib="webworker" />
import type { TimelineRequest, TimelineResponse } from "./types";

type WorkerInput = {
  type: "evaluate";
  payload: TimelineRequest;
};

type WorkerOutput =
  | { type: "result"; payload: TimelineResponse }
  | { type: "error"; error: string };

self.onmessage = async (event: MessageEvent<WorkerInput>) => {
  const message = event.data;
  if (!message || message.type !== "evaluate") {
    return;
  }

  try {
    const response = await fetch("/api/v1/timeline/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(message.payload)
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `HTTP ${response.status}`);
    }

    const payload = (await response.json()) as TimelineResponse;
    const result: WorkerOutput = { type: "result", payload };
    self.postMessage(result);
  } catch (error) {
    const messageText = error instanceof Error ? error.message : String(error);
    const out: WorkerOutput = { type: "error", error: messageText };
    self.postMessage(out);
  }
};

export {};
