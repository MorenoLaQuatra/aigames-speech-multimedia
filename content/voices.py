"""Default phrases for game 2 ("voices"): short, funny, school-appropriate
sentences the cloned voices will say. Short is better: generation time grows
with length, and on CPU every extra second of audio counts."""

from extensions import db
from models import VoicePhrase

PHRASES_IT = [
    "Oggi la verifica di matematica è stata rimandata a data da destinarsi.",
    "Ho visto un pinguino in bicicletta davanti alla scuola.",
    "Confesso: sono stato io a mangiare l'ultima fetta di pizza.",
    "Il mio gatto ha imparato a usare il computer meglio di me.",
    "Domani porto i cannoli per tutta la classe!",
    "Attenzione: il professore sta arrivando con un sacco di compiti.",
    "Ho sognato di vincere i mondiali di nuoto in una piscina di gelato.",
    "Secondo me gli alieni sono già tra noi, ma sono timidi.",
    "La mia canzone preferita? Quella che canta mia nonna in cucina.",
    "Non ho fatto i compiti perché il cane si è mangiato il quaderno.",
    "Da grande voglio fare l'astronauta, ma solo il sabato.",
    "Questa frase non l'ho mai detta, eppure è la mia voce.",
    "Il pranzo di oggi era buonissimo, chiedo il bis!",
    "Ho contato tutte le stelle del cielo: sono tantissime.",
    "Facciamo una gara: chi arriva ultimo offre il gelato.",
    "L'intelligenza artificiale mi ha appena rubato la voce.",
    "Mi sono svegliato alle cinque per vedere l'alba sull'Etna.",
    "Il mio superpotere è addormentarmi in qualsiasi posto.",
    "Ho scritto una poesia per la mia pianta di basilico.",
    "In gita voglio sedermi in fondo al pullman.",
    "Le arancine sono meglio degli arancini, e non si discute.",
    "Ieri ho parlato con un pappagallo che conosceva il latino.",
    "Se piove domani, giochiamo a calcio in palestra.",
    "Ho perso le chiavi di casa dentro il frigorifero.",
    "Questa mattina il caffè l'ha preparato il robot.",
    "Il mio piatto preferito è la pasta alla Norma.",
    "Ho una notizia fantastica: niente compiti per le vacanze!",
    "Chi ha spostato la mia merenda? Voglio la verità.",
    "Ho insegnato al mio cane a fare il saluto militare.",
    "Stasera guardo le stelle cadenti e esprimo tre desideri.",
    "Il professore ha detto che sono un genio, ma forse scherzava.",
    "Vado a fare una passeggiata sulla luna, torno per cena.",
]

PHRASES_EN = [
    "Today's maths test has been postponed until further notice.",
    "I saw a penguin riding a bicycle in front of the school.",
    "I confess: I ate the last slice of pizza.",
    "My cat can use the computer better than I can.",
    "Tomorrow I'm bringing cake for the whole class!",
    "I dreamt I won a swimming race in a pool of ice cream.",
    "I think aliens are already among us, but they're shy.",
    "I didn't do my homework because the dog ate my notebook.",
    "When I grow up I want to be an astronaut, but only on Saturdays.",
    "I never said this sentence, and yet it's my voice.",
    "Artificial intelligence just stole my voice.",
    "My superpower is falling asleep anywhere.",
    "I wrote a poem for my basil plant.",
    "I lost my house keys inside the fridge.",
    "Who moved my snack? I want the truth.",
]


def seed():
    if VoicePhrase.query.first() is not None:
        return "voices: phrases already present, skipped"
    for text in PHRASES_IT:
        db.session.add(VoicePhrase(text=text, language="it"))
    for text in PHRASES_EN:
        db.session.add(VoicePhrase(text=text, language="en"))
    db.session.commit()
    return f"voices: added {len(PHRASES_IT)} Italian and {len(PHRASES_EN)} English phrases"
