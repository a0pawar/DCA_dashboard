import pandas as pd
import numpy as np
import plotly.express as px
from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output
from flask_caching import Cache

# Initialize the Dash app
app = Dash(__name__)
server = app.server

# Configure cache
cache = Cache(app.server, config={
    'CACHE_TYPE': 'simple',  # You can use 'redis' or 'filesystem' for production
    'CACHE_DEFAULT_TIMEOUT': 300  # Cache timeout in seconds (5 minutes)
})

# Load and preprocess data (Cached function)
@cache.memoize()
def load_data():
    df = pd.read_excel('dca_data.xlsx', sheet_name="State_Consolidated_TimeSeries").iloc[54:76, 1:].T.reset_index()
    cols = df.iloc[0, 1:]
    index = df.iloc[1:, 0]
    df = df.iloc[1:, 1:]
    df.columns = cols
    df.index = index
    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    df = df[~df.index.weekday.isin([5, 6])]
    df = df.resample("W-FRI").mean()

    # Melt the dataframe
    df_long = df.reset_index().melt(
        id_vars=['index'],
        value_vars=['Rice', 'Wheat', 'Atta(wheat)', 'Gram Dal', 'Tur/Arhar Dal', 'Urad Dal',
                    'Moong Dal', 'Masoor Dal', 'Ground Nut Oil', 'Mustard Oil', 'Vanaspati',
                    'Soya Oil', 'Sunflower Oil', 'Palm Oil', 'Potato', 'Onion', 'Tomato',
                    'Sugar', 'Gur', 'Milk', 'Tea', 'Salt'],
        var_name='Commodity',
        value_name='Price'
    )

    # Rename the 'index' column to 'Date'
    df_long = df_long.rename(columns={'index': 'Date'})

    # Sort and reset the index
    df_long = df_long.sort_values(['Date', 'Commodity']).reset_index(drop=True)
    df_long['Date'] = pd.to_datetime(df_long['Date'])

    return df_long

# Load data from cache
df_long = load_data()

# Get the min and max dates for the slider
min_date = df_long['Date'].min()
max_date = df_long['Date'].max()
three_months_ago = max_date - pd.DateOffset(months=3)
df_long['Days'] = (df_long['Date'] - min_date).dt.days

# Filter the data for the last three months by default
df_long_default = df_long[df_long['Date'] >= three_months_ago]

# App layout
app.layout = html.Div([
    html.H1("Commodity Price Evolution Dashboard", style={'textAlign': 'center', 'color': '#2C3E50', 'backgroundColor': '#E6E6FA', 'padding': '10px', 'margin': '0'}),

    html.Div([
        html.Div([
            dcc.Dropdown(
                id='commodity-dropdown',
                options=[{'label': i, 'value': i} for i in df_long['Commodity'].unique()],
                value=[df_long['Commodity'].unique()[0]],
                multi=True
            ),
            dcc.Checklist(
                id='normalize-checkbox',
                options=[{'label': 'Normalize prices to 100', 'value': 'normalize'}],
                value=[]
            ),
            dcc.RangeSlider(
                id='date-slider',
                min=0,
                max=(max_date - min_date).days,
                value=[(three_months_ago - min_date).days, (max_date - min_date).days],
                marks={0: min_date.strftime('%Y-%m-%d'), (max_date - min_date).days: max_date.strftime('%Y-%m-%d')},
                step=1
            ),
            html.Div(id='slider-output-container'),
            dcc.Graph(id='price-evolution-graph'),
        ], style={'width': '60%', 'display': 'inline-block', 'padding': '10px'}),

        html.Div([
            html.H3("Week-on-Week Momentum", style={'textAlign': 'center', 'color': '#2980B9', 'backgroundColor': '#E6E6FA', 'padding': '10px', 'margin': '0'}),
            dash_table.DataTable(
                id='pct-change-table',
                style_table={'overflowX': 'auto'},
                style_cell={
                    'textAlign': 'center',
                    'padding': '5px',
                    'backgroundColor': '#E6E6FA',
                    'color': 'black',
                    'minWidth': '80px', 'width': '80px', 'maxWidth': '80px',
                    'overflow': 'hidden',
                    'textOverflow': 'ellipsis',
                },
                style_header={
                    'backgroundColor': '#2980B9',
                    'color': 'white',
                    'fontWeight': 'bold',
                    'whiteSpace': 'normal',
                    'height': 'auto',
                },
                style_data_conditional=[
                    {
                        'if': {'row_index': 'odd'},
                        'backgroundColor': '#F8E0E6',
                    }
                ],
            )
        ], style={'width': '38%', 'display': 'inline-block', 'padding': '10px', 'borderLeft': '1px solid #BDC3C7'})
    ], style={'display': 'flex', 'backgroundColor': '#E6E6FA', 'justifyContent': 'space-between'})
], style={'backgroundColor': '#E6E6FA', 'padding': '10px'})

# Callback to update the slider output
@app.callback(
    Output('slider-output-container', 'children'),
    [Input('date-slider', 'value')]
)
def update_slider_output(value):
    start_date = (min_date + pd.Timedelta(days=value[0])).strftime('%Y-%m-%d')
    end_date = (min_date + pd.Timedelta(days=value[1])).strftime('%Y-%m-%d')
    return f'Selected date range: {start_date} to {end_date}'

# Callback to update the graph and table
@app.callback(
    [Output('price-evolution-graph', 'figure'),
     Output('pct-change-table', 'data'),
     Output('pct-change-table', 'columns')],
    [Input('commodity-dropdown', 'value'),
     Input('normalize-checkbox', 'value'),
     Input('date-slider', 'value')]
)
def update_graph_and_table(selected_commodities, normalize, selected_date_range):
    if not selected_commodities:
        return {}, [], []

    start_date = min_date + pd.Timedelta(days=selected_date_range[0])
    end_date = min_date + pd.Timedelta(days=selected_date_range[1])

    # Load full data only if the user expands the date range beyond the default
    if start_date < three_months_ago:
        filtered_df_long = df_long[(df_long['Commodity'].isin(selected_commodities)) &
                                   (df_long['Date'] >= start_date) &
                                   (df_long['Date'] <= end_date)]
    else:
        filtered_df_long = df_long_default[(df_long_default['Commodity'].isin(selected_commodities)) &
                                           (df_long_default['Date'] >= start_date) &
                                           (df_long_default['Date'] <= end_date)]

    if 'normalize' in normalize:
        normalized_df_list = []
        for commodity in selected_commodities:
            commodity_df = filtered_df_long[filtered_df_long['Commodity'] == commodity].copy()
            starting_price = commodity_df['Price'].iloc[0]
            commodity_df['Price'] = (commodity_df['Price'] / starting_price) * 100
            normalized_df_list.append(commodity_df)
        filtered_df_long = pd.concat(normalized_df_list)

    fig = px.line(filtered_df_long, x='Date', y='Price', color='Commodity',
                  title=f'Price Evolution of {", ".join(selected_commodities)}')
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5))

    latest_4_weeks_df = filtered_df_long.groupby('Commodity').apply(lambda x: x.tail(5)).reset_index(drop=True)
    pct_change_table_data = []
    for commodity in selected_commodities:
        commodity_df = latest_4_weeks_df[latest_4_weeks_df['Commodity'] == commodity].copy()
        commodity_df['Pct_Change'] = commodity_df['Price'].pct_change() * 100
        pct_change_table_data.append(commodity_df.tail(4))

    if pct_change_table_data:
        pct_change_df = pd.concat(pct_change_table_data)[['Commodity', 'Date', 'Pct_Change']].dropna()
        pct_change_df['Date'] = pd.to_datetime(pct_change_df['Date'])
        pct_change_wide = pct_change_df.pivot(index='Commodity', columns='Date', values='Pct_Change')
        column_dates = pct_change_wide.columns.strftime('%d-%m-%y')
        pct_change_wide.columns = ['Three weeks ago', 'Two weeks ago', 'Previous week', 'Latest week']
        pct_change_wide = pct_change_wide.reset_index()
        pct_change_wide = pct_change_wide.round(2)
        pct_change_table_data = pct_change_wide.to_dict('records')
        pct_change_table_columns = [
            {'name': ['Commodity', ''], 'id': 'Commodity'},
            {'name': ['Three weeks ago', f'({column_dates[0]})'], 'id': 'Three weeks ago'},
            {'name': ['Two weeks ago', f'({column_dates[1]})'], 'id': 'Two weeks ago'},
            {'name': ['Previous week', f'({column_dates[2]})'], 'id': 'Previous week'},
            {'name': ['Latest week', f'({column_dates[3]})'], 'id': 'Latest week'}
        ]
    else:
        pct_change_table_data = []
        pct_change_table_columns = []

    return fig, pct_change_table_data, pct_change_table_columns

if __name__ == '__main__':
    app.run_server(debug=True, host='0.0.0.0', port=8050)
