import os
import threading
import json
import time
import traceback
from queue import Queue

# Kivy imports
try:
    from kivy.app import App
    from kivy.lang import Builder
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.tabbedpanel import TabbedPanel
    from kivy.clock import Clock
    from kivy.properties import StringProperty, ListProperty, NumericProperty, BooleanProperty
    from kivy.utils import mainthread
except ImportError:
    # Fallback for environment without Kivy (for editing/development)
    class App: pass
    def mainthread(f): return f
    class Clock:
        @staticmethod
        def schedule_once(f, dt): pass
    class StringProperty:
        def __init__(self, default=""): pass
    class ListProperty:
        def __init__(self, default=[]): pass
    class NumericProperty:
        def __init__(self, default=0): pass
    class BooleanProperty:
        def __init__(self, default=False): pass
    class TabbedPanel: pass
    class BoxLayout: pass
    def Builder_load_string(s): pass
    Builder = type('Builder', (), {'load_string': Builder_load_string})

# Project imports
try:
    from web_scraper_requests import RequestScraper
    from downloader import download_file
except ImportError:
    RequestScraper = None
    download_file = None

# Kivy String Definition (KV Language)
KV = """
<MainLayout>:
    do_default_tab: False
    
    TabbedPanelItem:
        text: 'Global'
        BoxLayout:
            orientation: 'vertical'
            padding: 10
            spacing: 10
            
            Label:
                text: "Global Settings"
                size_hint_y: None
                height: 40
                bold: True

            BoxLayout:
                size_hint_y: None
                height: 40
                Label:
                    text: "Website:"
                    size_hint_x: 0.3
                Spinner:
                    id: site_spinner
                    text: 'Select'
                    values: root.site_list
                    on_text: root.on_site_change(self.text)

            BoxLayout:
                size_hint_y: None
                height: 40
                Label:
                    text: "Output Dir:"
                    size_hint_x: 0.3
                TextInput:
                    id: output_dir_input
                    text: root.output_dir
                    readonly: True
                Button:
                    text: "Browse"
                    size_hint_x: 0.2
                    on_release: root.open_file_browser()

            Widget: # Spacer

    TabbedPanelItem:
        text: 'Movie'
        BoxLayout:
            orientation: 'vertical'
            padding: 10
            spacing: 10
            
            BoxLayout:
                size_hint_y: None
                height: 50
                TextInput:
                    id: movie_search_input
                    multiline: False
                    hint_text: "Search Movie..."
                Button:
                    text: "Search"
                    size_hint_x: 0.2
                    on_release: root.start_movie_search(movie_search_input.text)
            
            ScrollView:
                Label:
                    id: movie_results_label
                    text: "Search results will appear here"
                    size_hint_y: None
                    height: self.texture_size[1]
                    halign: 'left'
                    valign: 'top'
                    text_size: self.width, None
            
            Button:
                text: "Add Selected to Queue"
                size_hint_y: None
                height: 50
                on_release: root.add_movie_to_queue()

    TabbedPanelItem:
        text: 'TV Series'
        BoxLayout:
            orientation: 'vertical'
            padding: 10
            spacing: 10
            
            BoxLayout:
                size_hint_y: None
                height: 50
                TextInput:
                    id: tv_search_input
                    multiline: False
                    hint_text: "Search Series..."
                Button:
                    text: "Search"
                    size_hint_x: 0.2
                    on_release: root.start_tv_search(tv_search_input.text)
            
            BoxLayout:
                orientation: 'horizontal'
                spacing: 5
                # Simple selection placeholders using Buttons/Labels for prototype
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_x: 0.3
                    Label:
                        text: "Series"
                        size_hint_y: None
                        height: 30
                        bold: True
                    ScrollView:
                        Label:
                            id: series_results_label
                            text: "No series found"
                            size_hint_y: None
                            height: self.texture_size[1]
                            text_size: self.width, None
                            halign: 'left'

                BoxLayout:
                    orientation: 'vertical'
                    size_hint_x: 0.2
                    Label:
                        text: "Seasons"
                        size_hint_y: None
                        height: 30
                        bold: True
                    ScrollView:
                        Label:
                            id: seasons_results_label
                            text: "-"
                            size_hint_y: None
                            height: self.texture_size[1]
                            text_size: self.width, None
                            halign: 'center'

                BoxLayout:
                    orientation: 'vertical'
                    size_hint_x: 0.5
                    Label:
                        text: "Episodes"
                        size_hint_y: None
                        height: 30
                        bold: True
                    ScrollView:
                        Label:
                            id: episodes_results_label
                            text: "Select a series"
                            size_hint_y: None
                            height: self.texture_size[1]
                            text_size: self.width, None
                            halign: 'left'
            
            Button:
                text: "Add Selected Episodes to Queue"
                size_hint_y: None
                height: 50
                on_release: root.add_series_to_queue()

    TabbedPanelItem:
        text: 'Queue'
        BoxLayout:
            orientation: 'vertical'
            padding: 10
            spacing: 10
            
            Label:
                text: "Download Queue"
                size_hint_y: None
                height: 40
            
            ScrollView:
                Label:
                    id: queue_label
                    text: root.queue_text
                    size_hint_y: None
                    height: self.texture_size[1]
                    text_size: self.width, None
            
            ProgressBar:
                id: progress_bar
                max: 100
                value: root.progress_value
                size_hint_y: None
                height: 20
            
            Button:
                text: "Start Downloads"
                size_hint_y: None
                height: 50
                on_release: root.start_queue_processing()
"""

class MainLayout(TabbedPanel):
    site_list = ListProperty([])
    output_dir = StringProperty("downloads")
    queue_text = StringProperty("Queue is empty")
    progress_value = NumericProperty(0)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.scraper = None
        self.download_queue_list = []
        Clock.schedule_once(self.init_app, 0)

    def init_app(self, dt):
        try:
            if RequestScraper:
                self.scraper = RequestScraper()
                self.site_list = list(self.scraper.config.get("websites", {}).keys())
            App.get_running_app().status_text = "Ready."
        except Exception as e:
            App.get_running_app().status_text = f"Init Error: {e}"

    def on_site_change(self, site_name):
        App.get_running_app().status_text = f"Site changed to {site_name}"

    def open_file_browser(self):
        App.get_running_app().status_text = "File browser not implemented in prototype"

    def start_movie_search(self, query):
        if not query: return
        App.get_running_app().status_text = f"Searching for {query}..."
        threading.Thread(target=self._perform_search, args=(query,), daemon=True).start()

    def _perform_search(self, query):
        try:
            site = self.ids.site_spinner.text
            if self.scraper:
                results = self.scraper.search_website(site, query)
                self.update_movie_results(results)
            else:
                self.set_status("Scraper not initialized")
        except Exception as e:
            self.set_status(f"Search failed: {e}")

    @mainthread
    def update_movie_results(self, results):
        self.ids.movie_results_label.text = "\n".join([r['title'] for r in results])
        App.get_running_app().status_text = f"Found {len(results)} results"

    def start_tv_search(self, query):
        if not query: return
        App.get_running_app().status_text = f"Searching for {query}..."
        threading.Thread(target=self._perform_tv_search, args=(query,), daemon=True).start()

    def _perform_tv_search(self, query):
        try:
            site = self.ids.site_spinner.text
            if self.scraper:
                results = self.scraper.search_website(site, query)
                self.update_tv_results(results)
            else:
                self.set_status("Scraper not initialized")
        except Exception as e:
            self.set_status(f"TV Search failed: {e}")

    @mainthread
    def update_tv_results(self, results):
        self.ids.series_results_label.text = "\n".join([r['title'] for r in results])
        App.get_running_app().status_text = f"Found {len(results)} series"

    @mainthread
    def set_status(self, text):
        App.get_running_app().status_text = text

    def add_movie_to_queue(self):
        self.queue_text = "Movie added to queue (Prototype)"

    def add_series_to_queue(self):
        self.queue_text = "Series items added to queue (Prototype)"

    def start_queue_processing(self):
        self.progress_value = 0
        App.get_running_app().status_text = "Starting downloads..."

class VideoDownloaderApp(App):
    status_text = StringProperty("Initializing...")
    
    def build(self):
        Builder.load_string(KV)
        parent = BoxLayout(orientation='vertical')
        self.main_layout = MainLayout()
        parent.add_widget(self.main_layout)
        
        # Inline Status Label (Footer)
        from kivy.uix.label import Label
        self.status_label = Label(
            text=self.status_text, 
            size_hint_y=None, 
            height=40,
            color=(0.7, 0.7, 0.7, 1)
        )
        parent.add_widget(self.status_label)
        
        # Bind status_text to label
        self.bind(status_text=self._update_status_label)
        
        return parent

    def _update_status_label(self, instance, value):
        self.status_label.text = value

if __name__ == '__main__':
    # Only run if Kivy is actually available
    try:
        import kivy
        VideoDownloaderApp().run()
    except ImportError:
        print("Kivy not installed. Use this file as a template for Android deployment.")
