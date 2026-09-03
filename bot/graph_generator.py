import io
import datetime
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from database.models import SessionLocal, DetectedEvent
from sqlalchemy import func

def generate_analytics_graph(hours: int = 24) -> io.BytesIO:
    """Generates a graph of events over the last 24 hours."""
    db = SessionLocal()
    try:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        events = db.query(
            DetectedEvent.detected_at,
            DetectedEvent.event_type
        ).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike('test%')
        ).all()
        
        if not events:
            return None

        # Convert to pandas DataFrame
        df = pd.DataFrame(events, columns=['timestamp', 'event_type'])
        
        # Convert timestamp to Kyiv time (+3)
        df['timestamp'] = pd.to_datetime(df['timestamp']) + pd.Timedelta(hours=3)
        
        # Plot styling
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))
        
        colors = {
            "explosion": "#FF4136",        
            "direct_strike": "#FF0000",    
            "fire": "#FF851B",             
            "radar_track": "#FFDC00",      
            "general_alert": "#0074D9",    
            "armed_conflict": "#B10DC9"    
        }
        
        # Group by hour and event type
        df['hour'] = df['timestamp'].dt.floor('H')
        grouped = df.groupby(['hour', 'event_type']).size().unstack(fill_value=0)
        
        # Ensure all types exist in the plot if they are in colors
        for c in grouped.columns:
            if c not in colors:
                colors[c] = "#AAAAAA" # Default gray
                
        # Stacked bar chart
        grouped.plot(kind='bar', stacked=True, ax=ax, color=[colors.get(x) for x in grouped.columns])
        
        ax.set_title("Активність загроз (Київський час)", fontsize=16, pad=15)
        ax.set_xlabel("Година", fontsize=12)
        ax.set_ylabel("Кількість подій", fontsize=12)
        
        # Format X axis labels to be HH:MM
        labels = [item.strftime('%H:00') for item in grouped.index]
        ax.set_xticklabels(labels, rotation=45)
        
        # Legend translation
        translations = {
            "explosion": "Вибухи",
            "direct_strike": "Влучання",
            "fire": "Пожежі",
            "radar_track": "Шахеди/Ракети",
            "general_alert": "Тривоги/Зведення",
            "armed_conflict": "ППО/Зіткнення"
        }
        handles, lbls = ax.get_legend_handles_labels()
        new_labels = [translations.get(l, l) for l in lbls]
        ax.legend(handles, new_labels, title="Тип події")
        
        plt.tight_layout()
        
        # Save to BytesIO
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        buf.seek(0)
        buf.name = "analytics_graph.png"
        
        plt.close(fig)
        return buf
        
    finally:
        db.close()
