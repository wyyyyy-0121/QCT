"""Preserve v1; reject unverified boolean coercion in referenced aggregates."""
from formulaguard.formula import Func, Ref, Range
from dependency_execution_dev31 import Executor as ExecutorV1, Unsupported

VERSION = 'bounded-dependency-execution-dev31-v2-conservative-boolean-aggregates'


class Executor(ExecutorV1):
    def _eval(self, node, sheet, ctx):
        if isinstance(node, Func) and node.name in ('SUM', 'MAX', 'MIN'):
            for arg in node.args:
                if isinstance(arg, Range):
                    values = (self._cell(k, ctx) for k in self.range_keys(arg, sheet)[0])
                elif isinstance(arg, Ref):
                    values = [self._cell(self.ref(arg, sheet), ctx)]
                else:
                    continue
                if any(isinstance(value, bool) for value in values):
                    raise Unsupported('aggregate_boolean_coercion_unverified')
        return super()._eval(node, sheet, ctx)
