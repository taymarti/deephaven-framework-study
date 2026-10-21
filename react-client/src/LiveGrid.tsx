import { useEffect, useState } from 'react';
import type { dh as DhType } from '@deephaven/jsapi-types';
import { useApi } from '@deephaven/jsapi-bootstrap';
import { IrisGrid, IrisGridModelFactory, type IrisGridModel } from '@deephaven/iris-grid';
import { LoadingOverlay } from '@deephaven/components';

/**
 * Wraps @deephaven/iris-grid: the same canvas grid the Deephaven IDE (and
 * deephaven.ui's ui.table) uses - sorting, filtering, column ops, live ticks.
 * The model takes ownership of the table and closes it on unmount.
 */
export function LiveGrid({ fetchTable }: { fetchTable: () => Promise<DhType.Table> }) {
  const dh = useApi();
  const [model, setModel] = useState<IrisGridModel>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let m: IrisGridModel | undefined;
    let cancelled = false;
    setModel(undefined);
    fetchTable()
      .then(table => IrisGridModelFactory.makeModel(dh, table))
      .then(newModel => {
        if (cancelled) newModel.close();
        else setModel((m = newModel));
      })
      .catch(e => setError(`${e}`));
    return () => {
      cancelled = true;
      m?.close();
    };
  }, [dh, fetchTable]);

  if (model == null) {
    return <LoadingOverlay isLoading={error == null} isLoaded={false} errorMessage={error ?? null} />;
  }
  return <IrisGrid model={model} />;
}
