RUNNING THE FANTASY RANKING MODEL:

Within folder: Models/final position group data

    Run PositionalData.ipynb
    (Produces: PickleFiles/final_qb_data.pkl, final_rb_data.pkl, final_wrte_data.pkl)

Within folder: Models/Roster Creation

    Run Rosters.ipynb
    (Produces: PickleFiles/currYearRoster.pkl, PickleFiles/teamsPastRoster.pkl,
               webapp/data/teamsPastRoster.pkl)

Within folder: Models

    Run MLModel.ipynb
    (Produces: PickleFiles/QBDFForModelPPR.pkl, RBDFForModelPPR.pkl, WRTEDFForModelPPR.pkl
               and Half PPR / Non PPR variants)

    Run PredictionCode.ipynb
    (Produces: PickleFiles/QBs_PPR.pkl, RBs_PPR.pkl, WRTE_PPR.pkl and Half PPR / Non PPR variants)

Within folder: Models/Final Rankings

    Run RankingCSVCreation.ipynb
    (Produces: PickleFiles/Full PPR Rankings.pkl, Half PPR Rankings.pkl, Non PPR Rankings.pkl)

    Run VBD.ipynb
    (Produces: PickleFiles/Full PPR Rankings with Weighted VBD.pkl and Half PPR / Non PPR variants)

Within folder: Models/NewModel

    Run Phase1_BuildDataset.ipynb
    (Produces: PickleFiles/NewModel/qb_dataset.pkl, rb_dataset.pkl, wr_dataset.pkl, te_dataset.pkl)

    Run Phase2_FeatureEngineering.ipynb
    (Produces: PickleFiles/NewModel/qb_features.pkl, rb_features.pkl, wr_features.pkl, te_features.pkl)

    Run Phase3_TrainModels.ipynb
    (Produces: PickleFiles/NewModel/combined_predictions_ppr.pkl — used by the rankings page)

Within folder: webapp

    Run csvtosql.py

    Run python3 app.py

Note:

The NewModel pipeline (Phases 1-3) powers the main rankings page and mock draft.
The old pipeline (MLModel -> PredictionCode -> Final Rankings) powers the player profile stats pages
and the saved rankings feature. Both pipelines must be run for full app functionality.

The years in PositionalData.ipynb and Phase1_BuildDataset.ipynb should match.
Currently both use 2016-2025 (range(2016, 2026)).

Team grades on player profiles are computed live from nflreadpy on app startup — no pkl file needed.

VBD.ipynb has the model rankings weighted at 30% and ESPN ADP at 70%.
These weights can be changed as desired.

Use python3 (not python) to run csvtosql.py and app.py — requires Python 3.11 with nflreadpy installed.

RUNNING THE WEB APP:

Run python3 app.py
