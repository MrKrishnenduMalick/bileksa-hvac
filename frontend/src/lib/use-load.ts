"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type State<T> = { data: T | null; error: string | null; loading: boolean };

/** Load data on mount (and when `deps` change) with loading/error state and a reload(). */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const loaderRef = useRef(loader);
  const key = JSON.stringify(deps);

  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    let alive = true;
    loaderRef
      .current()
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch(
        (e: unknown) =>
          alive &&
          setState({
            data: null,
            error: e instanceof Error ? e.message : "Could not load data",
            loading: false,
          }),
      );
    return () => {
      alive = false;
    };
  }, [key]);

  const reload = useCallback(async () => {
    try {
      const data = await loaderRef.current();
      setState({ data, error: null, loading: false });
    } catch (e) {
      setState((s) => ({
        ...s,
        error: e instanceof Error ? e.message : "Could not load data",
        loading: false,
      }));
    }
  }, []);

  const setData = useCallback((data: T) => setState((s) => ({ ...s, data })), []);
  return { ...state, reload, setData };
}
