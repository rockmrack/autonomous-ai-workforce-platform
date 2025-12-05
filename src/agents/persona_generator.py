"""
Persona Generator - Creates realistic human personas for agents
Enhanced with diverse backgrounds and regional authenticity
"""

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import structlog

from src.llm.client import LLMClient, get_llm_client
from .models import AgentCapability

logger = structlog.get_logger(__name__)


@dataclass
class GeneratedPersona:
    """Complete generated persona for an agent"""

    # Basic info
    first_name: str
    last_name: str
    email: str
    timezone: str

    # Background
    age: int
    country: str
    city: str
    native_language: str
    additional_languages: list[str]

    # Professional
    education: str
    years_experience: int
    previous_roles: list[str]
    specializations: list[str]

    # Personality
    bio: str
    personality_traits: list[str]
    communication_style: str
    working_style: str

    # Writing style
    writing_style: dict

    # Working hours (in local timezone)
    working_hours: dict

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


# Regional name pools for authenticity
NAME_POOLS = {
    "us": {
        "first_names": {
            "male": ["James", "Michael", "Robert", "David", "William", "John", "Daniel", "Matthew", "Christopher", "Andrew", "Ryan", "Brandon", "Tyler", "Kevin", "Jason"],
            "female": ["Emily", "Sarah", "Jessica", "Ashley", "Amanda", "Jennifer", "Stephanie", "Nicole", "Elizabeth", "Megan", "Rachel", "Lauren", "Samantha", "Brittany", "Katherine"],
        },
        "last_names": ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Anderson", "Taylor", "Thomas", "Moore", "Jackson", "White", "Harris", "Clark", "Lewis", "Walker"],
    },
    "uk": {
        "first_names": {
            "male": ["Oliver", "Harry", "George", "Jack", "Jacob", "Noah", "Charlie", "Thomas", "Oscar", "William", "James", "Henry", "Leo", "Alfie", "Joshua"],
            "female": ["Olivia", "Emma", "Sophia", "Isabella", "Mia", "Charlotte", "Amelia", "Emily", "Harper", "Evelyn", "Abigail", "Ella", "Scarlett", "Grace", "Victoria"],
        },
        "last_names": ["Smith", "Jones", "Williams", "Taylor", "Brown", "Davies", "Evans", "Wilson", "Thomas", "Roberts", "Johnson", "Lewis", "Walker", "Robinson", "Wood", "Thompson", "White", "Watson", "Jackson", "Wright"],
    },
    "india": {
        "first_names": {
            "male": ["Arjun", "Aditya", "Rahul", "Vikram", "Rohan", "Karan", "Nikhil", "Sanjay", "Amit", "Prashant", "Raj", "Varun", "Ankit", "Deepak", "Manish"],
            "female": ["Priya", "Anjali", "Neha", "Pooja", "Divya", "Shreya", "Ananya", "Kavita", "Meera", "Nisha", "Riya", "Simran", "Tanvi", "Aishwarya", "Sakshi"],
        },
        "last_names": ["Sharma", "Patel", "Singh", "Kumar", "Gupta", "Verma", "Joshi", "Mehta", "Shah", "Reddy", "Nair", "Iyer", "Rao", "Kapoor", "Malhotra", "Agarwal", "Chopra", "Khanna", "Bhatia", "Saxena"],
    },
    "philippines": {
        "first_names": {
            "male": ["Juan", "Jose", "Miguel", "Carlos", "Antonio", "Rafael", "Gabriel", "Daniel", "Marco", "Paolo", "Christian", "Mark", "John", "Kevin", "Ryan"],
            "female": ["Maria", "Ana", "Isabel", "Sofia", "Gabriela", "Angela", "Patricia", "Christina", "Michelle", "Jennifer", "Nicole", "Jessica", "Angelica", "Jasmine", "Camille"],
        },
        "last_names": ["Santos", "Reyes", "Cruz", "Garcia", "Ramos", "Mendoza", "Torres", "Flores", "Rivera", "Gonzales", "Bautista", "Villanueva", "Fernandez", "Lopez", "Martinez", "Castillo", "Aquino", "Navarro", "Diaz", "Santiago"],
    },
    "eastern_europe": {
        "first_names": {
            "male": ["Alexander", "Dmitri", "Ivan", "Mikhail", "Nikolai", "Sergei", "Andrei", "Viktor", "Alexei", "Pavel", "Anton", "Maksim", "Roman", "Yuri", "Oleg"],
            "female": ["Anna", "Maria", "Elena", "Natalia", "Olga", "Svetlana", "Irina", "Katerina", "Tatiana", "Yulia", "Alexandra", "Victoria", "Daria", "Anastasia", "Sofia"],
        },
        "last_names": ["Petrov", "Ivanov", "Kuznetsov", "Popov", "Sokolov", "Lebedev", "Kozlov", "Novikov", "Morozov", "Volkov", "Alexeev", "Fedorov", "Mikhailov", "Vasiliev", "Pavlov"],
    },
}

CITIES_BY_REGION = {
    "us": [
        ("New York", "America/New_York"),
        ("Los Angeles", "America/Los_Angeles"),
        ("Chicago", "America/Chicago"),
        ("Houston", "America/Chicago"),
        ("Phoenix", "America/Phoenix"),
        ("Austin", "America/Chicago"),
        ("Denver", "America/Denver"),
        ("Seattle", "America/Los_Angeles"),
        ("Boston", "America/New_York"),
        ("Atlanta", "America/New_York"),
    ],
    "uk": [
        ("London", "Europe/London"),
        ("Manchester", "Europe/London"),
        ("Birmingham", "Europe/London"),
        ("Leeds", "Europe/London"),
        ("Bristol", "Europe/London"),
    ],
    "india": [
        ("Mumbai", "Asia/Kolkata"),
        ("Bangalore", "Asia/Kolkata"),
        ("Delhi", "Asia/Kolkata"),
        ("Hyderabad", "Asia/Kolkata"),
        ("Chennai", "Asia/Kolkata"),
        ("Pune", "Asia/Kolkata"),
    ],
    "philippines": [
        ("Manila", "Asia/Manila"),
        ("Cebu City", "Asia/Manila"),
        ("Davao City", "Asia/Manila"),
        ("Quezon City", "Asia/Manila"),
    ],
    "eastern_europe": [
        ("Kyiv", "Europe/Kiev"),
        ("Warsaw", "Europe/Warsaw"),
        ("Bucharest", "Europe/Bucharest"),
        ("Prague", "Europe/Prague"),
        ("Budapest", "Europe/Budapest"),
    ],
}

EDUCATION_TEMPLATES = [
    "Bachelor's degree in {field} from {university}",
    "Master's degree in {field}",
    "Self-taught with {years}+ years of hands-on experience",
    "Bachelor's in {field}, currently pursuing Master's",
    "Associate degree in {field} with professional certifications",
]

CAPABILITY_FIELDS = {
    AgentCapability.WEB_RESEARCH: ["Information Science", "Library Science", "Communications", "Journalism"],
    AgentCapability.CONTENT_WRITING: ["English Literature", "Creative Writing", "Communications", "Journalism", "Marketing"],
    AgentCapability.SEO_WRITING: ["Digital Marketing", "Communications", "Marketing", "Business"],
    AgentCapability.CODE_PYTHON: ["Computer Science", "Software Engineering", "Data Science", "Mathematics"],
    AgentCapability.CODE_JAVASCRIPT: ["Computer Science", "Web Development", "Software Engineering"],
    AgentCapability.DATA_ENTRY: ["Business Administration", "Office Administration", "Information Systems"],
    AgentCapability.DATA_ANALYSIS: ["Statistics", "Data Science", "Mathematics", "Economics", "Business Analytics"],
    AgentCapability.VIRTUAL_ASSISTANT: ["Business Administration", "Communications", "Office Management"],
    AgentCapability.TRANSLATION: ["Linguistics", "Modern Languages", "Translation Studies", "International Studies"],
}


class PersonaGenerator:
    """
    Generates realistic, diverse personas for AI agents.

    Features:
    - Regional name authenticity
    - Skill-appropriate backgrounds
    - Varied writing styles
    - Realistic work histories
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or get_llm_client()

    async def generate_persona(
        self,
        capabilities: list[AgentCapability],
        region: Optional[str] = None,
        gender: Optional[str] = None,
        experience_level: str = "mid",  # junior, mid, senior
    ) -> GeneratedPersona:
        """
        Generate a complete persona for an agent.

        Args:
            capabilities: Primary capabilities for the agent
            region: Geographic region (us, uk, india, philippines, eastern_europe)
            gender: Preferred gender (male, female) or None for random
            experience_level: Experience level (junior, mid, senior)

        Returns:
            Complete GeneratedPersona
        """
        # Select region if not specified
        if not region:
            region = random.choice(list(NAME_POOLS.keys()))

        # Select gender if not specified
        if not gender:
            gender = random.choice(["male", "female"])

        # Generate name
        name_pool = NAME_POOLS[region]
        first_name = random.choice(name_pool["first_names"][gender])
        last_name = random.choice(name_pool["last_names"])

        # Select city and timezone
        city, timezone = random.choice(CITIES_BY_REGION[region])

        # Generate age based on experience
        age_ranges = {
            "junior": (22, 28),
            "mid": (26, 38),
            "senior": (32, 50),
        }
        min_age, max_age = age_ranges.get(experience_level, (26, 38))
        age = random.randint(min_age, max_age)

        # Years of experience
        years_exp_ranges = {
            "junior": (1, 3),
            "mid": (3, 7),
            "senior": (7, 15),
        }
        min_exp, max_exp = years_exp_ranges.get(experience_level, (3, 7))
        years_experience = random.randint(min_exp, max_exp)

        # Generate education
        primary_capability = capabilities[0] if capabilities else AgentCapability.VIRTUAL_ASSISTANT
        fields = CAPABILITY_FIELDS.get(primary_capability, ["Business"])
        field = random.choice(fields)
        education = random.choice(EDUCATION_TEMPLATES).format(
            field=field,
            university="a reputable university",
            years=years_experience,
        )

        # Generate email
        email_domain = random.choice(["gmail.com", "outlook.com", "yahoo.com", "protonmail.com"])
        email_formats = [
            f"{first_name.lower()}.{last_name.lower()}",
            f"{first_name.lower()}{last_name.lower()}",
            f"{first_name.lower()}.{last_name.lower()}{random.randint(1, 99)}",
            f"{first_name[0].lower()}{last_name.lower()}",
        ]
        email = f"{random.choice(email_formats)}@{email_domain}"

        # Generate bio using LLM
        bio = await self._generate_bio(
            first_name=first_name,
            capabilities=capabilities,
            years_experience=years_experience,
            city=city,
            region=region,
        )

        # Generate writing style
        writing_style = self._generate_writing_style(experience_level, region)

        # Generate working hours (with some variation)
        working_hours = self._generate_working_hours(region)

        # Languages
        native_language = self._get_native_language(region)
        additional_languages = ["English"] if native_language != "English" else []

        # Personality traits
        personality_traits = self._generate_personality_traits()

        # Previous roles
        previous_roles = await self._generate_previous_roles(
            capabilities, years_experience
        )

        return GeneratedPersona(
            first_name=first_name,
            last_name=last_name,
            email=email,
            timezone=timezone,
            age=age,
            country=self._region_to_country(region),
            city=city,
            native_language=native_language,
            additional_languages=additional_languages,
            education=education,
            years_experience=years_experience,
            previous_roles=previous_roles,
            specializations=[c.value for c in capabilities],
            bio=bio,
            personality_traits=personality_traits,
            communication_style=random.choice([
                "professional", "friendly", "concise", "detailed"
            ]),
            working_style=random.choice([
                "methodical", "creative", "deadline-driven", "collaborative"
            ]),
            writing_style=writing_style,
            working_hours=working_hours,
        )

    async def _generate_bio(
        self,
        first_name: str,
        capabilities: list[AgentCapability],
        years_experience: int,
        city: str,
        region: str,
    ) -> str:
        """Generate a professional bio using LLM"""
        capability_names = [c.value.replace("_", " ") for c in capabilities]

        prompt = f"""Generate a brief, professional bio (2-3 sentences) for a freelancer with these details:
- Name: {first_name}
- Location: {city}
- Skills: {', '.join(capability_names)}
- Experience: {years_experience} years

The bio should:
- Be written in first person
- Sound natural and human
- Highlight key skills without being boastful
- Be suitable for a freelance platform profile

Return only the bio text, no quotes or additional formatting."""

        response = await self.llm.generate(
            prompt=prompt,
            max_tokens=200,
            temperature=0.8,
        )

        return response.strip()

    async def _generate_previous_roles(
        self,
        capabilities: list[AgentCapability],
        years_experience: int,
    ) -> list[str]:
        """Generate plausible previous job roles"""
        role_templates = {
            AgentCapability.CONTENT_WRITING: [
                "Content Writer at {company}",
                "Freelance Blogger",
                "Marketing Content Specialist",
                "Staff Writer",
            ],
            AgentCapability.CODE_PYTHON: [
                "Python Developer at {company}",
                "Backend Developer",
                "Data Engineer",
                "Software Developer",
            ],
            AgentCapability.DATA_ENTRY: [
                "Data Entry Specialist",
                "Administrative Assistant",
                "Office Coordinator",
                "Records Clerk",
            ],
            AgentCapability.VIRTUAL_ASSISTANT: [
                "Executive Assistant",
                "Virtual Assistant",
                "Administrative Coordinator",
                "Office Manager",
            ],
        }

        # Get relevant role templates
        templates = []
        for cap in capabilities:
            templates.extend(role_templates.get(cap, ["Freelancer"]))

        # Number of previous roles based on experience
        num_roles = min(years_experience // 2, 4)
        num_roles = max(num_roles, 1)

        companies = ["a tech startup", "a marketing agency", "a consulting firm", "an e-commerce company"]

        roles = []
        for _ in range(num_roles):
            template = random.choice(templates)
            role = template.format(company=random.choice(companies))
            if role not in roles:
                roles.append(role)

        return roles

    def _generate_writing_style(self, experience_level: str, region: str) -> dict:
        """Generate writing style configuration"""
        # Base style
        style = {
            "formality": random.choice(["casual", "professional", "semi-formal"]),
            "verbosity": random.choice(["concise", "moderate", "detailed"]),
            "uses_emojis": random.random() < 0.3,
            "uses_contractions": random.random() > 0.3,
            "paragraph_length": random.choice(["short", "medium", "long"]),
        }

        # Adjust based on region (subtle differences)
        if region == "uk":
            style["spelling"] = "british"
            style["uses_contractions"] = random.random() > 0.5
        else:
            style["spelling"] = "american"

        # Adjust based on experience
        if experience_level == "senior":
            style["formality"] = random.choice(["professional", "semi-formal"])
            style["verbosity"] = random.choice(["moderate", "detailed"])

        return style

    def _generate_working_hours(self, region: str) -> dict:
        """Generate realistic working hours"""
        # Base working hours with variation
        start_hour = random.randint(7, 10)
        end_hour = random.randint(17, 20)

        # Working days (most work weekdays, some include weekends)
        if random.random() < 0.2:
            days = [1, 2, 3, 4, 5, 6]  # Include Saturday
        else:
            days = [1, 2, 3, 4, 5]  # Weekdays only

        return {
            "start": start_hour,
            "end": end_hour,
            "days": days,
        }

    def _generate_personality_traits(self) -> list[str]:
        """Generate 3-5 personality traits"""
        traits = [
            "detail-oriented",
            "creative",
            "analytical",
            "organized",
            "proactive",
            "adaptable",
            "collaborative",
            "self-motivated",
            "curious",
            "patient",
            "reliable",
            "efficient",
        ]
        return random.sample(traits, random.randint(3, 5))

    def _get_native_language(self, region: str) -> str:
        """Get native language for region"""
        languages = {
            "us": "English",
            "uk": "English",
            "india": random.choice(["Hindi", "English"]),
            "philippines": "Filipino",
            "eastern_europe": random.choice(["Ukrainian", "Polish", "Romanian", "Russian"]),
        }
        return languages.get(region, "English")

    def _region_to_country(self, region: str) -> str:
        """Convert region code to country name"""
        countries = {
            "us": "United States",
            "uk": "United Kingdom",
            "india": "India",
            "philippines": "Philippines",
            "eastern_europe": random.choice(["Ukraine", "Poland", "Romania", "Czech Republic"]),
        }
        return countries.get(region, "United States")
