RUNNING THE FANTASY RANKING MODEL:

Download the 'Models' folder
    
Within folder: Roster Creation

    Run Rosters.ipynb (Creates current year roster and past rosters for last 10 seasons)
    
Within folder: progress position group data

    Run PositionalData.ipynb
    
Within folder: final position group data

    Run OverallStats.ipynb
    
Within folder: Models

    Run MLModel.ipynb (Creates the MLModel to be run in the prediction code)
    
    Run PredictionCode.ipynb (Current Year predictions for the MLModel to use)
    
Within folder: Final Rankings

    Run RankingsCSVCreation.ipynb (Makes the rankings from prediction code)
    
    Run VBD.ipynb (adds VBD and ADP weights to rankings)
    
Final Rankings -> Full/Half/Non PPR Rankings with Weighted WBD.csv


Note:

In Rosters.ipynb, you can adjust the years you want to use for current year roster and past rosters

The Years in Rosters.ipynb and PositionalData.ipynb should be the same years, so ensure they are the same for all the code to work.

Lastly, VBD.ipynb has merged the model created rankings at 30% and ESPN ADP at 70%. These weights can be changed to whatever you like as well.

RUNNING THE WEB APP:

Run app.py

