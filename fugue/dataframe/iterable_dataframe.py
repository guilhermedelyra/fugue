from typing import Any, Dict, Iterable, List, Optional

from fugue.dataframe.array_dataframe import ArrayDataFrame
from fugue.dataframe.dataframe import (
    DataFrame,
    LocalBoundedDataFrame,
    LocalUnboundedDataFrame,
    _get_schema_change,
)
from fugue.exceptions import FugueDataFrameOperationError
from triad.collections.schema import Schema
from triad.utils.iter import EmptyAwareIterable, make_empty_aware
from triad.utils.pyarrow import apply_schema


class IterableDataFrame(LocalUnboundedDataFrame):
    """DataFrame that wraps native python iterable of arrays. Please read
    |DataFrameTutorial| to understand the concept

    :param df: 2-dimensional array, iterable of arrays, or
      :class:`~fugue.dataframe.dataframe.DataFrame`
    :param schema: |SchemaLikeObject|

    .. admonition:: Examples

        >>> a = IterableDataFrame([[0,'a'],[1,'b']],"a:int,b:str")
        >>> b = IterableDataFrame(a)

    .. note::

        It's ok to peek the dataframe, it will not affect the iteration, but it's
        invalid operation to count
    """

    def __init__(self, df: Any = None, schema: Any = None):  # noqa: C901
        if df is None:
            idf: Iterable[Any] = []
            orig_schema: Optional[Schema] = None
        elif isinstance(df, IterableDataFrame):
            idf = df.native
            orig_schema = df.schema
        elif isinstance(df, DataFrame):
            idf = df.as_array_iterable(type_safe=False)
            orig_schema = df.schema
        elif isinstance(df, Iterable):
            idf = df
            orig_schema = None
        else:
            raise ValueError(f"{df} is incompatible with IterableDataFrame")
        schema, pos = _get_schema_change(orig_schema, schema)
        super().__init__(schema)
        self._pos = pos
        self._native = make_empty_aware(self._preprocess(idf))

    @property
    def native(self) -> EmptyAwareIterable[Any]:
        """Iterable of native python arrays"""
        return self._native

    @property
    def empty(self) -> bool:
        return self.native.empty

    def peek_array(self) -> List[Any]:
        self.assert_not_empty()
        return list(self.native.peek())

    def head(
        self, n: int, columns: Optional[List[str]] = None
    ) -> LocalBoundedDataFrame:
        res: List[Any] = []
        for row in self.as_array_iterable(columns, type_safe=True):
            if n < 1:
                break
            res.append(list(row))
            n -= 1
        return ArrayDataFrame(
            res, self.schema if columns is None else self.schema.extract(columns)
        )

    def _drop_cols(self, cols: List[str]) -> DataFrame:
        return IterableDataFrame(self, self.schema - cols)

    def _select_cols(self, keys: List[Any]) -> DataFrame:
        return IterableDataFrame(self, self.schema.extract(keys))

    def rename(self, columns: Dict[str, str]) -> DataFrame:
        try:
            schema = self.schema.rename(columns)
        except Exception as e:
            raise FugueDataFrameOperationError from e
        return IterableDataFrame(self.native, schema)

    def alter_columns(self, columns: Any) -> DataFrame:
        new_schema = self.schema.alter(columns)
        if new_schema == self.schema:
            return self
        return IterableDataFrame(self.native, new_schema)

    def as_local_bounded(self) -> LocalBoundedDataFrame:
        return ArrayDataFrame(self.as_array(), schema=self.schema)

    def as_array(
        self, columns: Optional[List[str]] = None, type_safe: bool = False
    ) -> List[Any]:
        return list(self.as_array_iterable(columns, type_safe=type_safe))

    def as_array_iterable(
        self, columns: Optional[List[str]] = None, type_safe: bool = False
    ) -> Iterable[Any]:
        if columns is None:
            if not type_safe:
                for item in self.native:
                    yield item
            else:
                for item in apply_schema(
                    self.schema.pa_schema,
                    self.native,
                    copy=True,
                    deep=True,
                    str_as_json=True,
                ):
                    yield item
        else:
            df = IterableDataFrame(self, self.schema.extract(columns))
            for item in df.as_array_iterable(type_safe=type_safe):
                yield item

    def _preprocess(self, raw_data: Iterable[Any]) -> Iterable[Any]:
        if len(self._pos) == 0:
            for x in raw_data:
                yield x
        else:
            for x in raw_data:
                yield [x[i] for i in self._pos]
