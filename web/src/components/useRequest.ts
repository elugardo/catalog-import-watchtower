import { useEffect, useState, type DependencyList } from "react";
import { errorMessage } from "../api/client";

export type RequestState<T> = { kind: "loading" } | { kind: "ready"; data: T } | { kind: "error"; message: string };

/**
 * Run one request when the component mounts (and again when `deps` change),
 * and keep its outcome. The error text is the one error path from
 * `client.ts`. A response for an earlier set of `deps` is dropped.
 */
export function useRequest<T>(load: () => Promise<T>, deps: DependencyList): RequestState<T> {
  const [state, setState] = useState<RequestState<T>>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    load()
      .then((data) => {
        if (!cancelled) setState({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ kind: "error", message: errorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
    // `load` is a fresh closure on every render; `deps` says when it changes.
  }, deps);

  return state;
}
