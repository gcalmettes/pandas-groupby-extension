import pandas as pd
import numpy as np
import json
from functools import reduce

@pd.api.extensions.register_dataframe_accessor("gc")
@pd.api.extensions.register_series_accessor("gc")
class GroupByPipedTransforms(object):
    def __init__(self, pandas_obj):
        self._validate(pandas_obj)
        self._obj = self._convertToDataFrame(pandas_obj)
        self._pipedFunctions = []
        
    def __repr__(self):
        return "<CustomGroupBy object>"
    
    def __call__(self, renameCol="Value"):
        self._obj = self._rename(self._obj, renameCol)
        return self

    @staticmethod
    def _validate(obj):
        if not isinstance(obj, (pd.DataFrame, pd.Series)):
            raise AttributeError("The object must be a pandas DataFrame or Series.")
    
    @staticmethod
    def _convertToDataFrame(obj, colName="Value"):
        if isinstance(obj, pd.Series):
            outDf = pd.DataFrame({colName: obj.values.ravel()}, index=obj.index)
        else:
            outDf = obj.copy()
        return outDf
    
    @staticmethod
    def _rename(obj, colName):
        outDf = obj
        if len(obj.columns) == 1:
            outDf = pd.DataFrame({colName: obj.values.ravel()}, index=obj.index)
        return outDf
    
    @staticmethod
    def _validatePipelineObject(obj):
        if not isinstance(obj, (pd.core.groupby.generic.DataFrameGroupBy, pd.core.groupby.generic.SeriesGroupBy)):
            raise TypeError("A groupby operation has to be applied before a pipeline can be executed.")
    
    @staticmethod
    def _pipe(*funcs):
        '''Combine a list of functions with a pipe operator'''
        return lambda x: reduce(lambda f, g: g(f), list(funcs), x)
    
    @staticmethod
    def _resetIndex(df, resetPosition=0, handleFuture=True):
        '''Reset index using the given position as zero value'''
        isIndexTimeType = np.issubdtype(df.index, np.datetime64)
        func = lambda x: x - x[resetPosition]
        if isIndexTimeType and handleFuture:
            return df.set_index(keys=pd.to_datetime(func(df.index)))
        else:
            return df.set_index(keys=func(df.index))

    @staticmethod
    def _getIdxFrom(idx, idxList, axis):
        if idx in idxList and type(idx) == type(idxList[0]):
            # need the type checking as pd.to_datetime("1970-01-01 00:05:01") == 0
            pos = list(idxList).index(idx)
        elif not isinstance(idx, int):
            raise TypeError(f"{idx} is not a valid {'index' if axis=='index' else 'columns'} identifier.")
        elif isinstance(idx, int):
            pos = idx
        else:
            raise ValueError("An error occured when retrieving the index.")
        return pos

    def _execute(self, df, index=0, column=None, operation="subtract"):
        '''Apply a DataFrame-wise operation using the provided row (index) or column'''
        numericCols = df.select_dtypes(include=[np.number]).columns
        if column is None: # index-based indexing
          axis = 'index'
          pos = self._getIdxFrom(index, df.index, axis)
        else: # column-based indexing
          axis = 'columns'
          pos = self._getIdxFrom(column, numericCols, axis)
    
        # operation types
        if operation == "subtract":
            func = lambda x: x - x.iloc[pos]
        elif operation == "add":
            func = lambda x: x + x.iloc[pos]
        elif operation == "multiply":
            func = lambda x: x * x.iloc[pos]
        elif operation == "divide":
            func = lambda x: x / x.iloc[pos]
        else:
            raise ValueError("The provided operation to perform is not of subtract/add/multiply/divide")
        df.loc[:, numericCols] = df.loc[:, numericCols].apply(func, axis=axis)
        return df
            
    def groupby(self, grouper, **args):
        if not isinstance(self._obj, (pd.core.groupby.generic.DataFrameGroupBy, pd.core.groupby.generic.SeriesGroupBy)):
            self._obj = self._obj.groupby(grouper, **args)
        return self
    
    def pipe(self, *functions):
        '''Add function(s) to the pipeline'''
        self._pipedFunctions.extend(functions)
        return self
    
    def concat(self, multiIndex='hierarchy', sep='|', **kwargs):
        axis = kwargs.pop('axis', 1)
        self._validatePipelineObject(self._obj)
        concatenated = pd.concat(map(lambda x: self.pipeline(x[1]), self._obj), axis=axis, **kwargs)
        if axis == 1 and multiIndex == 'join':
            # create flat index and join group name at end of each column with separator in between
            newNames = map(lambda x: map(lambda y: f"{y}{sep}{x[0]}", x[1].columns), self._obj)
            newNames = [name for subset in newNames for name in subset]
            concatenated.columns = newNames
        if axis == 1 and multiIndex == 'hierarchy':
            # create multi index hierarchy for the columns
            newNames = map(lambda x: map(lambda y: (x[0],y), x[1].columns), self._obj)
            newNames = pd.MultiIndex.from_tuples([name for subset in newNames for name in subset])
            concatenated.columns = newNames
        if axis == 0 and multiIndex == 'join':
            # create flat index and join group name at end of each column with separator in between
            newNames = map(lambda x: map(lambda y: f"{y}{sep}{x[0]}", x[1].index), self._obj)
            newNames = [name for subset in newNames for name in subset]
            concatenated.index = newNames
        if axis == 0 and multiIndex == 'hierarchy':
            # create multi index hierarchy for the index
            newNames = map(lambda x: map(lambda y: (x[0],y), x[1].index), self._obj)
            newNames = pd.MultiIndex.from_tuples([name for subset in newNames for name in subset])
            concatenated.index = newNames
        self._pipedFunctions = [] # clear piped functions
        return concatenated
    
    def resetStartingValues(self):
        self.pipe(lambda x: self._execute(x, index=0, operation="subtract"))
        return self

    def subtract(self, index=0, column=None):
        self.pipe(lambda x: self._execute(x, index, column, operation="subtract"))
        return self

    def add(self, index=0, column=None):
        self.pipe(lambda x: self._execute(x, index, column, operation="add"))
        return self

    def multiply(self, index=0, column=None):
        self.pipe(lambda x: self._execute(x, index, column, operation="multiply"))
        return self

    def divide(self, index=0, column=None):
        self.pipe(lambda x: self._execute(x, index, column, operation="divide"))
        return self
    
    def resetIndex(self, handleFuture=True):
        self.pipe(self._resetIndex)
        return self
    
    def toJSON(self, fileName, rowIndicesFieldName='idx_', addMultiIndexWithSep='|', **kwargs):
        concatenated = self.concat(
            multiIndex="join" if addMultiIndexWithSep else False, 
            sep=addMultiIndexWithSep, 
            **kwargs)
        dict_toExport = concatenated.to_dict(orient="records")
        if rowIndicesFieldName:
            isIndexTimeType = np.issubdtype(concatenated.index, np.datetime64)
            for i,index in enumerate(concatenated.index):
                idx = index if not isIndexTimeType else index.isoformat()
                dict_toExport[i][rowIndicesFieldName] = f"{idx}"
        with open(fileName, "w") as f:
            f.write(f'{{"data": {json.dumps(dict_toExport)}}}')

    @property
    def pipeline(self):
      return self._pipe(*self._pipedFunctions)

    @property
    def transformedGroups(self):
      return list(map(lambda x: (x[0], self.pipeline(x[1])), self._obj))
                                    