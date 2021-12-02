# Copyright (c) Microsoft Corporation
# Licensed under the MIT License.

"""Defines the RAIInsights class."""

import json
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from responsibleai._input_processing import _convert_to_list
from responsibleai._interfaces import Dataset, RAIInsightsData
from responsibleai._internal.constants import ManagerNames, Metadata, SKLearn
from responsibleai._managers.causal_manager import CausalManager
from responsibleai._managers.counterfactual_manager import \
    CounterfactualManager
from responsibleai._managers.error_analysis_manager import ErrorAnalysisManager
from responsibleai._managers.explainer_manager import ExplainerManager
from responsibleai.exceptions import UserConfigValidationException
from responsibleai.rai_insights.constants import ModelTask

_DATA = 'data'
_DTYPES = 'dtypes'
_TRAIN = 'train'
_TEST = 'test'
_TARGET_COLUMN = 'target_column'
_TASK_TYPE = 'task_type'
_MODEL = Metadata.MODEL
_MODEL_PKL = _MODEL + '.pkl'
_SERIALIZER = 'serializer'
_CLASSES = 'classes'
_MANAGERS = 'managers'
_CATEGORICAL_FEATURES = 'categorical_features'
_META_JSON = Metadata.META_JSON
_TRAIN_LABELS = 'train_labels'
_JSON_EXTENSION = '.json'


class RAIInsights(object):

    """Defines the top-level Model Analysis API.
    Use RAIInsights to analyze errors, explain the most important
    features, compute counterfactuals and run causal analysis in a
    single API.
    :param model: The model to compute RAI insights for.
        A model that implements sklearn.predict or sklearn.predict_proba
        or function that accepts a 2d ndarray.
    :type model: object
    :param train: The training dataset including the label column.
    :type train: pandas.DataFrame
    :param test: The test dataset including the label column.
    :type test: pandas.DataFrame
    :param target_column: The name of the label column.
    :type target_column: str
    :param task_type: The task to run, can be `classification` or
        `regression`.
    :type task_type: str
    :param categorical_features: The categorical feature names.
    :type categorical_features: list[str]
    :param classes: The class labels in the training dataset
    :type classes: ndarray
    :param serializer: Picklable custom serializer with save and load
        methods for custom model serialization.
        The save method writes the model to file given a parent directory.
        The load method returns the deserialized model from the same
        parent directory.
    :type serializer: object
    """

    def __init__(self, model, train, test, target_column,
                 task_type, categorical_features=None, classes=None,
                 serializer=None,
                 maximum_rows_for_test: int = 5000):
        """Defines the top-level Model Analysis API.
        Use RAIInsights to analyze errors, explain the most important
        features, compute counterfactuals and run causal analysis in a
        single API.
        :param model: The model to compute RAI insights for.
            A model that implements sklearn.predict or sklearn.predict_proba
            or function that accepts a 2d ndarray.
        :type model: object
        :param train: The training dataset including the label column.
        :type train: pandas.DataFrame
        :param test: The test dataset including the label column.
        :type test: pandas.DataFrame
        :param target_column: The name of the label column.
        :type target_column: str
        :param task_type: The task to run, can be `classification` or
            `regression`.
        :type task_type: str
        :param categorical_features: The categorical feature names.
        :type categorical_features: list[str]
        :param classes: The class labels in the training dataset
        :type classes: ndarray
        :param serializer: Picklable custom serializer with save and load
            methods defined for model that is not serializable. The save
            method returns a dictionary state and load method returns the
            model.
        :type serializer: object
        :param maximum_rows_for_test: Limit on size of test data
            (for performance reasons)
        :type maximum_rows_for_test: int
        """
        self._validate_model_analysis_input_parameters(
            model=model, train=train, test=test,
            target_column=target_column, task_type=task_type,
            categorical_features=categorical_features,
            classes=classes,
            serializer=serializer,
            maximum_rows_for_test=maximum_rows_for_test)
        self.model = model
        self.train = train
        self.test = test
        self.target_column = target_column
        self.task_type = task_type
        self.categorical_features = categorical_features
        self._serializer = serializer
        self._classes = RAIInsights._get_classes(
            task_type=self.task_type,
            train=self.train,
            target_column=self.target_column,
            classes=classes
        )

        self._causal_manager = CausalManager(
            train, test, target_column, task_type, categorical_features)

        self._counterfactual_manager = CounterfactualManager(
            model=model, train=train, test=test,
            target_column=target_column, task_type=task_type,
            categorical_features=categorical_features)

        self._error_analysis_manager = ErrorAnalysisManager(
            model, test, target_column,
            self._classes,
            categorical_features)

        self._explainer_manager = ExplainerManager(
            model, train, test,
            target_column,
            self._classes,
            categorical_features=categorical_features)

        self._managers = [self._causal_manager,
                          self._counterfactual_manager,
                          self._error_analysis_manager,
                          self._explainer_manager]

    @staticmethod
    def _get_classes(task_type, train, target_column, classes):
        if task_type == ModelTask.CLASSIFICATION:
            if classes is None:
                classes = train[target_column].unique()
                # sort the classes after calling unique in numeric case
                classes.sort()
                return classes
            else:
                return classes
        else:
            return None

    def _validate_model_analysis_input_parameters(
            self, model, train, test, target_column,
            task_type, categorical_features, classes,
            serializer,
            maximum_rows_for_test: int):
        """
        Validate the inputs for RAIInsights class.

        :param model: The model to compute RAI insights for.
            A model that implements sklearn.predict or sklearn.predict_proba
            or function that accepts a 2d ndarray.
        :type model: object
        :param train: The training dataset including the label column.
        :type train: pandas.DataFrame
        :param test: The test dataset including the label column.
        :type test: pandas.DataFrame
        :param target_column: The name of the label column.
        :type target_column: str
        :param task_type: The task to run, can be `classification` or
            `regression`.
        :type task_type: str
        :param categorical_features: The categorical feature names.
        :type categorical_features: list[str]
        :param classes: The class labels in the training dataset
        :type classes: ndarray
        :param serializer: Picklable custom serializer with save and load
            methods defined for model that is not serializable. The save
            method returns a dictionary state and load method returns the
            model.
        :type serializer: object
        :param maximum_rows_for_test: Limit on size of test data
            (for performance reasons)
        :type maximum_rows_for_test: int
        """

        valid_tasks = [
            ModelTask.CLASSIFICATION.value,
            ModelTask.REGRESSION.value
        ]
        if task_type not in valid_tasks:
            message = (f"Unsupported task type '{task_type}'. "
                       f"Should be one of {valid_tasks}")
            raise UserConfigValidationException(message)

        if model is None:
            warnings.warn(
                'INVALID-MODEL-WARNING: No valid model is supplied. '
                'The explanations, error analysis and counterfactuals '
                'may not work')

        if serializer is not None:
            if not hasattr(serializer, 'save'):
                raise UserConfigValidationException(
                    'The serializer does not implement save()')

            if not hasattr(serializer, 'load'):
                raise UserConfigValidationException(
                    'The serializer does not implement load()')

            try:
                pickle.dumps(serializer)
            except Exception:
                raise UserConfigValidationException(
                    'The serializer should be serializable via pickle')

        if isinstance(train, pd.DataFrame) and isinstance(test, pd.DataFrame):
            if test.shape[0] > maximum_rows_for_test:
                msg_fmt = 'The test data has {0} rows, ' +\
                    'but limit is set to {1} rows. ' +\
                    'Please resample the test data or ' +\
                    'adjust maximum_rows_for_test'
                raise UserConfigValidationException(
                    msg_fmt.format(
                        test.shape[0], maximum_rows_for_test)
                )

            if len(set(train.columns) - set(test.columns)) != 0 or \
                    len(set(test.columns) - set(train.columns)):
                raise UserConfigValidationException(
                    'The features in train and test data do not match')

            if target_column not in list(train.columns) or \
                    target_column not in list(test.columns):
                raise UserConfigValidationException(
                    'Target name {0} not present in train/test data'.format(
                        target_column)
                )

            if categorical_features is not None and \
                    len(categorical_features) > 0:
                if target_column in categorical_features:
                    raise UserConfigValidationException(
                        'Found target name {0} in '
                        'categorical feature list'.format(
                            target_column)
                    )

                difference_set = set(categorical_features) - set(train.columns)
                if len(difference_set) > 0:
                    message = ("Feature names in categorical_features "
                               "do not exist in train data: "
                               f"{list(difference_set)}")
                    raise UserConfigValidationException(message)

            if classes is not None and task_type == \
                    ModelTask.CLASSIFICATION:
                if len(set(train[target_column].unique()) -
                       set(classes)) != 0 or \
                        len(set(classes) -
                            set(train[target_column].unique())) != 0:
                    raise UserConfigValidationException(
                        'The train labels and distinct values in '
                        'target (train data) do not match')

                if len(set(test[target_column].unique()) -
                       set(classes)) != 0 or \
                        len(set(classes) -
                            set(test[target_column].unique())) != 0:
                    raise UserConfigValidationException(
                        'The train labels and distinct values in '
                        'target (test data) do not match')

            if model is not None:
                # Pick one row from train and test data
                small_train_data = train.iloc[0:1].drop(
                    [target_column], axis=1)
                small_test_data = test.iloc[0:1].drop(
                    [target_column], axis=1)

                small_train_features_before = list(small_train_data.columns)

                # Run predict() of the model
                try:
                    model.predict(small_train_data)
                    model.predict(small_test_data)
                except Exception:
                    raise UserConfigValidationException(
                        'The model passed cannot be used for'
                        ' getting predictions via predict()'
                    )
                self._validate_features_same(small_train_features_before,
                                             small_train_data,
                                             SKLearn.PREDICT)

                # Run predict_proba() of the model
                if task_type == ModelTask.CLASSIFICATION:
                    try:
                        model.predict_proba(small_train_data)
                        model.predict_proba(small_test_data)
                    except Exception:
                        raise UserConfigValidationException(
                            'The model passed cannot be used for'
                            ' getting predictions via predict_proba()'
                        )
                self._validate_features_same(small_train_features_before,
                                             small_train_data,
                                             SKLearn.PREDICT_PROBA)

                if task_type == ModelTask.REGRESSION:
                    if hasattr(model, SKLearn.PREDICT_PROBA):
                        warnings.warn(
                            'INVALID-TASK-TYPE-WARNING: The regression model'
                            'provided has a predict_proba function. '
                            'Please check the task_type.')
        else:
            raise UserConfigValidationException(
                "Unsupported data type for either train or test. "
                "Expecting pandas Dataframe for train and test."
            )

    def _validate_features_same(self, small_train_features_before,
                                small_train_data, function):
        """
        Validate the features are unmodified on the dataframe.

        :param small_train_features_before: The features saved before
            an operation was performed.
        :type small_train_features_before: list[str]
        :param small_train_data: The dataframe after the operation.
        :type small_train_data: pandas.DataFrame
        :param function: The name of the operation performed.
        :type function: str
        """
        small_train_features_after = list(small_train_data.columns)
        if small_train_features_before != small_train_features_after:
            raise UserConfigValidationException(
                ('Calling model {} function modifies '
                 'input dataset features. Please check if '
                 'predict function is defined correctly.').format(function)
            )

    @property
    def causal(self) -> CausalManager:
        """Get the causal manager.
        :return: The causal manager.
        :rtype: CausalManager
        """
        return self._causal_manager

    @property
    def counterfactual(self) -> CounterfactualManager:
        """Get the counterfactual manager.
        :return: The counterfactual manager.
        :rtype: CounterfactualManager
        """
        return self._counterfactual_manager

    @property
    def error_analysis(self) -> ErrorAnalysisManager:
        """Get the error analysis manager.
        :return: The error analysis manager.
        :rtype: ErrorAnalysisManager
        """
        return self._error_analysis_manager

    @property
    def explainer(self) -> ExplainerManager:
        """Get the explainer manager.
        :return: The explainer manager.
        :rtype: ExplainerManager
        """
        return self._explainer_manager

    def compute(self):
        """Calls compute on each of the managers."""
        for manager in self._managers:
            manager.compute()

    def list(self):
        """List information about each of the managers.
        :return: Information about each of the managers.
        :rtype: dict
        """
        configs = {}
        for manager in self._managers:
            configs[manager.name] = manager.list()
        return configs

    def get(self):
        """List information about each of the managers.

        :return: Information about each of the managers.
        :rtype: dict
        """
        configs = {}
        for manager in self._managers:
            configs[manager.name] = manager.get()
        return configs

    def get_data(self):
        """Get all data as RAIInsightsData object

        :return: Model Analysis Data
        :rtype: RAIInsightsData
        """
        data = RAIInsightsData()
        data.dataset = self._get_dataset()
        data.modelExplanationData = self.explainer.get_data()
        data.errorAnalysisData = self.error_analysis.get_data()
        data.causalAnalysisData = self.causal.get_data()
        data.counterfactualData = self.counterfactual.get_data()
        return data

    def _get_dataset(self):
        dashboard_dataset = Dataset()
        dashboard_dataset.task_type = self.task_type
        dashboard_dataset.categorical_features = self.categorical_features
        dashboard_dataset.class_names = _convert_to_list(
            self._classes)

        predicted_y = None
        feature_length = None

        dataset: pd.DataFrame = self.test.drop(
            [self.target_column], axis=1)

        if isinstance(dataset, pd.DataFrame) and hasattr(dataset, 'columns'):
            self._dataframeColumns = dataset.columns
        try:
            list_dataset = _convert_to_list(dataset)
        except Exception as ex:
            raise ValueError(
                "Unsupported dataset type") from ex
        if dataset is not None and self.model is not None:
            try:
                predicted_y = self.model.predict(dataset)
            except Exception as ex:
                msg = "Model does not support predict method for given"
                "dataset type"
                raise ValueError(msg) from ex
            try:
                predicted_y = _convert_to_list(predicted_y)
            except Exception as ex:
                raise ValueError(
                    "Model prediction output of unsupported type,") from ex
        if predicted_y is not None:
            if(self.task_type == "classification" and
                    dashboard_dataset.class_names is not None):
                predicted_y = [dashboard_dataset.class_names.index(
                    y) for y in predicted_y]
            dashboard_dataset.predicted_y = predicted_y
        row_length = 0

        if list_dataset is not None:
            row_length, feature_length = np.shape(list_dataset)
            if row_length > 100000:
                raise ValueError(
                    "Exceeds maximum number of rows"
                    "for visualization (100000)")
            if feature_length > 1000:
                raise ValueError("Exceeds maximum number of features for"
                                 " visualization (1000). Please regenerate the"
                                 " explanation using fewer features or"
                                 " initialize the dashboard without passing a"
                                 " dataset.")
            dashboard_dataset.features = list_dataset

        true_y = self.test[self.target_column]

        if true_y is not None and len(true_y) == row_length:
            if(self.task_type == "classification" and
               dashboard_dataset.class_names is not None):
                true_y = [dashboard_dataset.class_names.index(
                    y) for y in true_y]
            dashboard_dataset.true_y = _convert_to_list(true_y)

        features = dataset.columns

        if features is not None:
            features = _convert_to_list(features)
            if feature_length is not None and len(features) != feature_length:
                raise ValueError("Feature vector length mismatch:"
                                 " feature names length differs"
                                 " from local explanations dimension")
            dashboard_dataset.feature_names = features
        dashboard_dataset.target_column = self.target_column
        if (self.model is not None and
                hasattr(self.model, SKLearn.PREDICT_PROBA) and
                self.model.predict_proba is not None and
                dataset is not None):
            try:
                probability_y = self.model.predict_proba(dataset)
            except Exception as ex:
                raise ValueError("Model does not support predict_proba method"
                                 " for given dataset type,") from ex
            try:
                probability_y = _convert_to_list(probability_y)
            except Exception as ex:
                raise ValueError(
                    "Model predict_proba output of unsupported type,") from ex
            dashboard_dataset.probability_y = probability_y

        return dashboard_dataset

    def _write_to_file(self, file_path, content):
        """Save the string content to the given file path.
        :param file_path: The file path to save the content to.
        :type file_path: str
        :param content: The string content to save.
        :type content: str
        """
        with open(file_path, 'w') as file:
            file.write(content)

    def save(self, path):
        """Save the RAIInsights to the given path.
        :param path: The directory path to save the RAIInsights to.
        :type path: str
        """
        top_dir = Path(path)
        # save each of the individual managers
        for manager in self._managers:
            manager._save(top_dir / manager.name)
        # save current state
        data_directory = Path(path) / _DATA
        data_directory.mkdir(parents=True, exist_ok=True)
        dtypes = self.train.dtypes.astype(str).to_dict()
        self._write_to_file(data_directory / (_TRAIN + _DTYPES),
                            json.dumps(dtypes))
        self._write_to_file(data_directory / (_TRAIN + _JSON_EXTENSION),
                            self.train.to_json(orient='split'))

        dtypes = self.test.dtypes.astype(str).to_dict()
        self._write_to_file(data_directory / (_TEST + _DTYPES),
                            json.dumps(dtypes))
        self._write_to_file(data_directory / (_TEST + _JSON_EXTENSION),
                            self.test.to_json(orient='split'))
        classes = _convert_to_list(self._classes)
        meta = {
            _TARGET_COLUMN: self.target_column,
            _TASK_TYPE: self.task_type,
            _CATEGORICAL_FEATURES: self.categorical_features,
            _CLASSES: classes
        }
        with open(top_dir / _META_JSON, 'w') as file:
            json.dump(meta, file)
        if self._serializer is not None:
            # save the model
            self._serializer.save(self.model, top_dir)
            # save the serializer
            with open(top_dir / _SERIALIZER, 'wb') as file:
                pickle.dump(self._serializer, file)
        else:
            if self.model is not None:
                has_setstate = hasattr(self.model, '__setstate__')
                has_getstate = hasattr(self.model, '__getstate__')
                if not (has_setstate and has_getstate):
                    raise ValueError(
                        "Model must be picklable or a custom serializer must"
                        " be specified")
            with open(top_dir / _MODEL_PKL, 'wb') as file:
                pickle.dump(self.model, file)

    @staticmethod
    def load(path):
        """Load the RAIInsights from the given path.
        :param path: The directory path to load the RAIInsights from.
        :type path: str
        :return: The RAIInsights object after loading.
        :rtype: RAIInsights
        """
        # create the RAIInsights without any properties using the __new__
        # function, similar to pickle
        inst = RAIInsights.__new__(RAIInsights)
        top_dir = Path(path)
        # load current state
        data_directory = Path(path) / _DATA
        with open(data_directory / (_TRAIN + _DTYPES), 'r') as file:
            types = json.load(file)
        with open(data_directory / (_TRAIN + _JSON_EXTENSION), 'r') as file:
            train = pd.read_json(file, dtype=types, orient='split')
        inst.__dict__[_TRAIN] = train
        with open(data_directory / (_TEST + _DTYPES), 'r') as file:
            types = json.load(file)
        with open(data_directory / (_TEST + _JSON_EXTENSION), 'r') as file:
            test = pd.read_json(file, dtype=types, orient='split')
        inst.__dict__[_TEST] = test
        with open(top_dir / _META_JSON, 'r') as meta_file:
            meta = meta_file.read()
        meta = json.loads(meta)
        inst.__dict__[_TARGET_COLUMN] = meta[_TARGET_COLUMN]
        inst.__dict__[_TASK_TYPE] = meta[_TASK_TYPE]
        inst.__dict__[_CATEGORICAL_FEATURES] = meta[_CATEGORICAL_FEATURES]
        classes = None
        if _TRAIN_LABELS in meta:
            classes = meta[_TRAIN_LABELS]
        else:
            classes = meta[_CLASSES]

        inst.__dict__['_' + _CLASSES] = RAIInsights._get_classes(
            task_type=meta[_TASK_TYPE],
            train=train,
            target_column=meta[_TARGET_COLUMN],
            classes=classes
        )

        serializer_path = top_dir / _SERIALIZER
        if serializer_path.exists():
            with open(serializer_path, 'rb') as file:
                serializer = pickle.load(file)
            inst.__dict__['_' + _SERIALIZER] = serializer
            inst.__dict__[_MODEL] = serializer.load(top_dir)
        else:
            inst.__dict__['_' + _SERIALIZER] = None
            with open(top_dir / _MODEL_PKL, 'rb') as file:
                inst.__dict__[_MODEL] = pickle.load(file)

        # load each of the individual managers
        manager_map = {
            ManagerNames.CAUSAL: CausalManager,
            ManagerNames.COUNTERFACTUAL: CounterfactualManager,
            ManagerNames.ERROR_ANALYSIS: ErrorAnalysisManager,
            ManagerNames.EXPLAINER: ExplainerManager,
        }
        managers = []
        for manager_name, manager_class in manager_map.items():
            full_name = f'_{manager_name}_manager'
            manager_dir = top_dir / manager_name
            manager = manager_class._load(manager_dir, inst)
            inst.__dict__[full_name] = manager
            managers.append(manager)

        inst.__dict__['_' + _MANAGERS] = managers
        return inst
