import pandas as pd
import numpy as np
import plotly.express as px
from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output
from flask_caching import Cache
import json
import requests
from bs4 import BeautifulSoup
import re

# Initialize the Dash app
app = Dash(__name__)
server = app.server

# Configure cache
cache = Cache(app.server, config={'CACHE_TYPE': 'simple', 'CACHE_DEFAULT_TIMEOUT': 300})

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

    df_long = df.reset_index().melt(
        id_vars=['index'],
        value_vars=['Rice', 'Wheat', 'Atta(wheat)', 'Gram Dal', 'Tur/Arhar Dal', 'Urad Dal',
                    'Moong Dal', 'Masoor Dal', 'Ground Nut Oil', 'Mustard Oil', 'Vanaspati',
                    'Soya Oil', 'Sunflower Oil', 'Palm Oil', 'Potato', 'Onion', 'Tomato',
                    'Sugar', 'Gur', 'Milk', 'Tea', 'Salt'],
        var_name='Commodity',
        value_name='Price'
    )

    df_long = df_long.rename(columns={'index': 'Date'})
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

# Load the GeoJSON file for Indian states
with open('india_states.geojson', 'r') as f:
    india_geojson = json.load(f)

# Function to fetch and process rainfall data
@cache.memoize()
def fetch_rainfall_data(rainfall_type):
    url = f"https://mausam.imd.gov.in/responsive/rainfallinformation_state.php?msg={rainfall_type}"
    response = requests.get(url)
    html = response.text

    soup = BeautifulSoup(html, 'html.parser')
    script_tag = soup.find('script', text=lambda t: t and 'var mapVar = AmCharts.parseGeoJSON' in t)
    data_start = script_tag.string.index('"areas": [')
    data_end = script_tag.string.index(']', data_start) + 1
    json_data = script_tag.string[data_start:data_end]

    json_data = json_data.replace('"areas": ', '')
    json_data = re.sub(r'(\w+):', r'"\1":', json_data)
    areas_data = json.loads(json_data)

    rainfall_data = []
    for area in areas_data:
        if area['id'] and area['id'] != 'null':
            state = area['title'].strip()
            balloon_data = extract_data(area['balloonText'])
            rainfall_data.append({
                'state': state,
                'actual': balloon_data['actual'],
                'normal': balloon_data['normal'],
                'deviation': balloon_data['deviation']
            })

    df = pd.DataFrame(rainfall_data)
    df['state'] = df['state'].apply(lambda x: x.title().replace(" (Ut)", "").replace("&", "and") if "Jammu" in x else x.title().replace(" (Ut)", ""))
    
    return df

# Helper function to extract data from the balloon text
def extract_data(balloon_text):
    actual = re.search(r'Actual : ([\d.]+) mm', balloon_text)
    normal = re.search(r'Normal : ([\d.]+) mm', balloon_text)
    departure = re.search(r'Departure : ([-\d]+)%', balloon_text)

    return {
        'actual': float(actual.group(1)) if actual else None,
        'normal': float(normal.group(1)) if normal else None,
        'deviation': int(departure.group(1)) if departure else None
    }

# App layout
app.layout = html.Div([
    html.H1("Inflation Monitoring Dashboard", style={'textAlign': 'center', 'marginBottom': '20px'}),
    dcc.Tabs([
        dcc.Tab(label='DCA Retail Price Trends', children=[
            html.Div([
                html.Div([
                    dcc.Dropdown(
                        id='commodity-dropdown',
                        options=[{'label': i, 'value': i} for i in df_long['Commodity'].unique()],
                        value=['Tomato', 'Potato', 'Onion'],
                        multi=True,
                        style={'marginBottom': '10px'}
                    ),
                    dcc.Checklist(
                        id='normalize-checkbox',
                        options=[{'label': 'Normalize prices to 100', 'value': 'normalize'}],
                        value=[],
                        style={'marginBottom': '10px'}
                    ),
                    dcc.RangeSlider(
                        id='date-slider',
                        min=0,
                        max=(max_date - min_date).days,
                        value=[(three_months_ago - min_date).days, (max_date - min_date).days],
                        marks={0: min_date.strftime('%Y-%m-%d'), (max_date - min_date).days: max_date.strftime('%Y-%m-%d')},
                        step=1
                    ),
                    html.Div(id='slider-output-container', style={'marginTop': '10px'}),
                    dcc.Graph(id='price-evolution-graph'),
                ], style={'width': '60%', 'display': 'inline-block', 'verticalAlign': 'top'}),
                html.Div([
                    html.H3("Week-on-Week Momentum (%)", style={'textAlign': 'center'}),
                    dash_table.DataTable(id='pct-change-table')
                ], style={'width': '38%', 'display': 'inline-block', 'verticalAlign': 'top', 'marginLeft': '2%'})
            ])
        ]),
        dcc.Tab(label='Rainfall Deviation', children=[
            html.Div([
                html.Label('Select Period:'),
                dcc.Dropdown(
                    id='rainfall-type-dropdown',
                    options=[
                        {'label': 'Daily', 'value': 'D'},
                        {'label': 'Weekly', 'value': 'W'},
                        {'label': 'Monthly', 'value': 'M'},
                        {'label': 'Cumulative', 'value': 'C'}
                    ],
                    value='M',
                    clearable=False,
                    style={'width': '50%', 'marginBottom': '20px'}
                ),
            ]),
            html.Div([
                html.Div([
                    dcc.Graph(id='rainfall-deviation-map')
                ], style={'width': '60%', 'display': 'inline-block', 'verticalAlign': 'top'}),
                html.Div([
                    dash_table.DataTable(id='rainfall-table')
                ], style={'width': '35%', 'display': 'inline-block', 'verticalAlign': 'top', 'marginLeft': '5%'})
            ])
        ])
    ])
])

# Callbacks for Commodity Price Evolution
@app.callback(
    Output('slider-output-container', 'children'),
    [Input('date-slider', 'value')]
)
def update_slider_output(value):
    start_date = (min_date + pd.Timedelta(days=value[0])).strftime('%Y-%m-%d')
    end_date = (min_date + pd.Timedelta(days=value[1])).strftime('%Y-%m-%d')
    return f'Selected date range: {start_date} to {end_date}'

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

# Callbacks for Rainfall Deviation
@app.callback(
    [Output('rainfall-deviation-map', 'figure'),
     Output('rainfall-table', 'data'),
     Output('rainfall-table', 'columns')],
    [Input('rainfall-type-dropdown', 'value')]
)
def update_rainfall_data(rainfall_type):
    df = fetch_rainfall_data(rainfall_type)
    
    fig = px.choropleth(
        df,
        geojson=india_geojson,
        locations='state',
        featureidkey='properties.ST_NM',
        color='deviation',
        hover_name='state',
        hover_data=['actual', 'normal'],
        color_continuous_scale='Blues',
        range_color=[-100, 100],
        title='Rainfall Deviation from Normal'
    )

    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(
        title_font=dict(size=24, family='Arial', color='darkblue'),
        title_x=0.5,
        title_y=0.95,
        margin={"r":0,"t":30,"l":0,"b":0},
        height=600,
        coloraxis_colorbar=dict(
            title="Deviation (%)",  # Set your custom color bar title here
            title_font=dict(size=14, family='Arial', color='darkblue')
        )
    )

    columns = [
        {"name": "State", "id": "state"},
        {"name": "Actual (mm)", "id": "actual"},
        {"name": "Normal (mm)", "id": "normal"},
        {"name": "Deviation (%)", "id": "deviation"}
    ]

    return fig, df.to_dict('records'), columns

if __name__ == '__main__':
    app.run_server(debug=True, host=0.0.0.0 ,port=8050)
