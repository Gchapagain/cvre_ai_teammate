"""Demo connections for licensed or partner-only data. They return made-up sample findings.

These services do not offer open access: Zillow's open API is retired, LinkedIn needs a formal
partnership, Redfin does not allow automated collection, and CoStar, LoopNet and Crexi data are
licensed. In production CBRE's own licence would connect here. Until then every finding below is
fake, carries simulated=True, is shown with a SIMULATED chip, and can never be accepted or counted.
"""

from services.connections.base import Adapter, finding

LICENSE_NOTE = "Needs licensed access - in production, CBRE's own license would connect here."


class DemoAdapter(Adapter):
    kind = "Licensed data (demo)"
    simulated = True
    default_enabled = False
    samples = ()  # (topic, summary, figure, metric)

    def search(self, deal):
        """No call to anyone: returns the made-up samples."""
        name = f"{self.name} (simulated)"
        return [finding(topic, f"SIMULATED SAMPLE, NOT REAL DATA: {summary}", name, 2, self.id, figure=figure,
                        metric=metric, date="sample", simulated=True)
                for topic, summary, figure, metric in self.samples]


class LinkedInDemo(DemoAdapter):
    id, name, icon = "demo_linkedin", "LinkedIn", ":material/badge:"
    topics = ("Employment and demand",)
    provides = "Hiring activity by employers near the property (demo)."
    samples = (("Employment and demand", "made-up count of warehouse job postings nearby: 111.", "111 postings", "job postings"),)


class CoStarDemo(DemoAdapter):
    id, name, icon = "demo_costar", "CoStar", ":material/apartment:"
    topics = ("Vacancy", "Asking rent trend")
    provides = "Submarket vacancy and asking rents (demo)."
    samples = (("Vacancy", "made-up submarket vacancy of 11.1%.", "11.1%", "vacancy rate"),
               ("Asking rent trend", "made-up average asking rent of $1.11 per SF.", "$1.11 per SF", "asking rent"))


class LoopNetCrexiDemo(DemoAdapter):
    id, name, icon = "demo_loopnet_crexi", "LoopNet / Crexi", ":material/storefront:"
    topics = ("New supply",)
    provides = "Listings and comparable properties on the market (demo)."
    samples = (("New supply", "made-up count of comparable listings: 11.", "11 listings", "comparable listings"),)


class ZillowDemo(DemoAdapter):
    id, name, icon = "demo_zillow", "Zillow", ":material/home:"
    topics = ("Population and income",)
    provides = "Residential context around the property (demo)."
    samples = (("Population and income", "made-up typical home value of $111,111.", "$111,111", "home value"),)


class RedfinDemo(DemoAdapter):
    id, name, icon = "demo_redfin", "Redfin", ":material/house:"
    topics = ("Population and income",)
    provides = "Residential sales activity around the property (demo)."
    samples = (("Population and income", "made-up count of nearby home sales last month: 11.", "11 sales", "home sales"),)
