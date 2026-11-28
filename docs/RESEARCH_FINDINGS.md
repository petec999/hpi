# HaierPi — dziennik badań i stan wiedzy (2026-11-28)

Zbiorcze ustalenia z analizy kodu, historii HA, pasywnego nasłuchu RS485 i testów jednej instalacji. Dokument pozwala kontynuować projekt po utracie historii rozmowy. Dane empiryczne nie są specyfikacją fabryczną ani dowodem oszczędności. Bez pełnych prywatnych logów, danych dostępowych i adresów sieciowych.

## 1. Stan projektu

- Repozytorium `petec999/hpi`, gałąź `feature/adaptive-storage-audit`, nakładka na HaierPi Stable 1.4.5.
- Ostatnia wersja funkcjonalna zweryfikowana w chwili sporządzenia dokumentu: [1feaf0c7900012277917c541531e2f5263adc87c](https://github.com/petec999/hpi/commit/1feaf0c7900012277917c541531e2f5263adc87c). Wszystkie cztery CI PASS: [Adaptive storage audit](https://github.com/petec999/hpi/actions/runs/46139881021), [diagnostic integration](https://github.com/petec999/hpi/actions/runs/46139881098), [Alpha13](https://github.com/petec999/hpi/actions/runs/46139881046), [core resources](https://github.com/petec999/hpi/actions/runs/46139881033). Testy nie zastępują odbioru na urządzeniu.
- Instalator: `install-adaptive-preview.sh`, najpierw `--dry-run`, następnie `--apply`. Kopia przed zmianą, sprawdzenie świeżych ramek i próba rollbacku. Po restarcie ręcznie wznowić istniejący Experiment, nie rozpoczynać od nowa.
- Kluczowe pliki: `adaptive/regulator.py`, `adaptive/live_runtime.py`, `adaptive/energy.py`, `tools/patch-adaptive-preview.py`. Panel `/v2/`, raport `/v2/adaptive-report`, rejestry `/v2/registers`.
- Analizy HA: [home-iot-telemetry/home_assistant](https://github.com/petec999/home-iot-telemetry/tree/main/home_assistant).
- CO i CWU traktować rozłącznie. W badanym okresie CWU przygotowywane poza pompą ciepła. Nie generalizować wyników CO na TANK; nie przywracać wycofanego eksperymentalnego writera A04.

## 2. Empiryczne częstotliwości sprężarki

Źródło: [frequency-report-90d.py, a13b37f](https://github.com/petec999/home-iot-telemetry/blob/a13b37f35b07a684eb8054a71a0f126fa1a2a766/home_assistant/frequency-report-90d.py). Próby minutowe, stabilny kontekst co najmniej 15 min, bez defrostu; dostępna historia, nie gwarantowane 90 dni. Raport nie odfiltrował niezależnie CWU. Brak randomizacji pogody i obciążenia.

| Tryb | FLimit | Minuty | Maks. Fact/Fset | Dominujący poziom |
|---|---|---:|---:|---|
| Eco | OFF | 473 | 67 Hz | 65 Hz: 372 min (78,6%) |
| Eco | ON | 1547 | 40 Hz | 40 Hz: 1414 min (91,4%) |
| Quiet | OFF | 178 | 65 Hz | 65 Hz: 147 min (82,6%) |
| Quiet | ON | 2750 | 40 Hz | 40 Hz: 1516 min (55,1%); 20 Hz: 263 min |
| Turbo | OFF | 268 | 65 Hz | 65 Hz: 93 min (34,7%) |
| Turbo | ON | 2112 | 45 Hz | 45 Hz: 2091 min (99,0%) |

Empiryczne poziomy odniesienia CO: FLimit ON Eco/Quiet 40 Hz, Turbo 45 Hz; OFF 65 Hz (Eco sporadycznie 67). Wszystkie obserwacje >=60 Hz w raporcie miały FLimit OFF. Defrost może osiągać 80 Hz, nie jest objęty modelem CO. Nie są to limity fabryczne.

**Pułapka:** surowy `sensor.haierpi_flrelay` zgłaszał stale 1 również przy zgodnym OFF `binary_sensor.haierpi_flimiton` i `switch.haierpi_flimit_relay`. Poprawiona analiza: 6409 min zgodnego ON i 919 min OFF przy flrelay=1. Grupować historię wg zgodnych sygnałów ON/OFF, nie samego flrelay; w kodzie weryfikować GPIO. Nie mylić starych encji z aktualnymi `haierpi_*`.

Praca ciągła nie oznacza prawidłowej modulacji. Fact i Fset bliskie limitu wraz z utrzymującym się niedoborem Two mogą świadczyć o braku wydajności. Sama niska częstotliwość nie dowodzi rezerwy mocy; sam limit nie dowodzi niedoboru.

## 3. Adaptive — wnioski i implementacja

Pierwotnie Experiment czekał na naturalny STOP przed zmianą konfiguracji. Przy długiej pracy ciągłej blokowało to następne konfiguracje (19/36 okien zaobserwowane podczas prac, nie bieżący stan).

- Zmiana dopuszczalna także podczas stabilnego CO: 15 min stabilizacji, świeże dane, zgodność Fact/Fset, brak priorytetów/defrostu/CWU, zapas do STOP, brak deficytu komfortu. Potwierdzony naturalny postój nadal jest alternatywą. Jedno wyjście naraz, ponowne sprawdzenie przed zapisem. Nie wymuszać START/STOP.
- Sześć konfiguracji Eco/Quiet/Turbo × FLimit OFF/ON. Każda: 3 zaakceptowane cykle lub 6 okien po 30 min; razem 18 cykli / 36 okien. Bez sztywnego terminu 7 dni; checkpointy.
- Ochrona komfortu: empirycznie Two niedobór 2 K / 30 min, spadek temp. domu 0,5 K / 10 min, minimum domu 19°C, ponowna próba przy warunkach cieplejszych o 2 K; szczegóły w aktualnej konfiguracji guard. Stabilizacja 15 min. Przy niedoborze najpierw zwalnianie FLimit zgodnie z polityką, potem odpowiedni preset. Nie wyłączać zabezpieczeń fabrycznych.
- Diagnostyka `limited_shortfall`, `limited_sufficient`, `modulating_shortfall`, `modulating_sufficient`, przejście/brak danych. Limit empiryczny z tolerancją 1 Hz przy zgodności Fact/Fset do 3 Hz. Niedobór odnosi się do Two, zachowano trendy i ochronę STOP.
- Okna eksperymentu: czas obserwowanej pracy, czas na limicie, czas limit+niedobór, średni Fact/Fset, średni dodatni niedobór Two. Starsze okna bez danych nie otrzymują sztucznych zer.
- `CapacityLearning`: pasywne konteksty temp. zewnętrzna × zadana (co 2 K) × tryb/FLimit; wykluczenie luk, CWU, defrostu, błędu i stabilizacji. Minimum 3 h ważonych obserwacji, w tym 30 min i >=20% czasu nasyconego niedoborem, pozwala pominąć opcjonalną próbę redukcji. Nie blokuje redukcji chroniącej przed STOP ani zwiększania mocy. Pamięć traci połowę wagi w 30 dni. Nie zakładać niezależności dni.
- Przygotowanie przed START: domyślnie Quiet+FLimit; zmiana według wystarczających świeżych danych o niedoborze domyślnego kontekstu i wystarczających danych o alternatywie. Bez wymuszania startu.
- Empiryczny START ok. zadana−2 K (Twi/Two idle proxy), STOP ok. zadana+5 K na Two. Nie są fabrycznie potwierdzonymi progami, ETA tylko ekstrapolacja.
- Otwarte: wielodniowy test rzeczywisty, trwały model cieplny budynku (dotąd trendy RAM), porównanie kontekstów Auto/Legacy, obserwacja odchyleń limitu Hz. Nie dodawać agresywnych zmian do aktywnego eksperymentu bez danych.

Punkty historii: [capacity guard 57c539d](https://github.com/petec999/hpi/commit/57c539ded7775d88322a17f47ac2d6766e9652cb), [capacity learning 5a68c09](https://github.com/petec999/hpi/commit/5a68c09f8265eb8bd954c3b3d07f2a137dda45fa), [startup a44025c](https://github.com/petec999/hpi/commit/a44025cc729790cd4ed3ba5ce2a0a1fb1f02f48d), [aging + energy 66fd62c](https://github.com/petec999/hpi/commit/66fd62cba9a0a01bd2f6d42f7a8d34767bd3a326).

## 4. Energia, HA, zasoby

- COP jest szacunkiem: przepływ wpisany ręcznie, nie zmierzony. Nie używać COP jako samodzielnego warunku sterowania. Elektryczna energia może być zmierzona lub estymowana. Podawać pokrycie sparowanych danych i pochodzenie pomiarów.
- Trwała historia energii: 2 K koszyki temp. zewnętrznej i zadanej oraz tryb/FLimit, netto ciepło z ujemną energią defrostu, COP tylko przy wymaganym pokryciu. Zmiana konfiguracji pomiarowej resetuje tę historię. Nie utożsamiać z całosezonowym COP.
- Raport HA V4, jedno okno 24 h: 17 startów, 1141,8 min pracy, 98,6% pokrycia, 5 pełnych cykli (średnio 89,5 min), 10 defrostów. 7 dni: 65 startów, 8106,1 min pracy, 98,1% pokrycia, 25 pełnych cykli (średnio 169,4 min, maks. 772,6 min), jeden pełny cykl <10 min, 46 defrostów. Starty obserwowane i pełne cykle to różne miary. Wspólne luki kompresor/defrost nie zawsze mają potwierdzoną przyczynę.
- HA recorder: historię TWO/TWI/TAO zastąpiono próbkami co 30 s, precyzja 0,1°C; zachowano surowe odczyty do sterowania i obliczeń na żywo. Potwierdzono brak nowych wpisów historii surowych encji i dalsze aktualizacje próbkowanych.
- [heating-daily-report.py V4](https://github.com/petec999/home-iot-telemetry/blob/6be5efff8fff2b6435168deed18ef04ac88edb2c/home_assistant/heating-daily-report.py), [dashboard final](https://github.com/petec999/home-iot-telemetry/blob/19272c55cc5b67704533cc8c5aaff039b909486a/home_assistant/dashboard-final-v1.py).
- W osobnej analizie CWU: cykle cyrkulacji >=15 min dawały wzrost T200 (mediana +9 K w badanej grupie), krótkie 1–5 min zwykle nie. Temperatura T100 i T200 zależy od przepływów i poboru, nie jest czystym pomiarem strat zbiornika.
- NanoPi, [host-resource-audit.py](../tools/host-resource-audit.py): próbka 60 s, CPU 13,29% jednego rdzenia, RSS 47,4 MiB, 6 wątków, 13 FD, wzrost RSS 20 KiB, 0 B zapisu dyskowego procesu w próbce, dostępne 72,9% RAM i 97,6% dysku. Kopie rollback ok. 24 MB. Brak przesłanek do agresywnej optymalizacji, ale minuta nie wyklucza wycieku ani nie mierzy zużycia SD.
- Istnieją ograniczenia kolejek MQTT, PUBACK, watchdog HA, CRC RS485 i ponowne otwarcie portu po zaniku ramek. Nie przebudowywać bez objawów.

## 5. RS485 YR-E27 — mapa i pewność

Adresy dziesiętne, słowo 16 bitów, H = starszy bajt, L = młodszy, bit 0 = najmłodszy bit słowa. Banki R101 (6 słów), R141 (16), R201 (1), R241 (22). Nie mylić z inną mapą Modbus producenta.

| Pole | Interpretacja | Status |
|---|---|---|
| R101 bit 3, 0x0008 | A04, polecenie grzałki | istniejące dekodowanie; nie stan wyjścia |
| R101 bit 7, 0x0080 | wybrany TANK | nie oznacza grzałki CWU |
| R141 bit 13, 0x2000 | defrost | istniejące dekodowanie |
| R144 bit 8, 0x0100 | A4A, sygnał grzałki | wskazanie sterownika, nie pomiar prądu |
| R144 bit 9, 0x0200 | pompa obiegowa | istniejące dekodowanie |
| R144H bez bitu 0 | kod 26 we wszystkich analizowanych próbkach 0–80 Hz | hipoteza faz sprężarki nie potwierdziła się |
| R150H | godziny od startu bieżącego cyklu; zerowanie późniejsze | powtarzalne obserwacje jednej instalacji |
| R151H | godziny bieżącego cyklu; zerowanie wcześniejsze | powtarzalne obserwacje jednej instalacji |
| R155 bit 4 | możliwa flaga ograniczenia mocy | niepotwierdzone; nie utożsamiać z FLimit |
| R156 bit 4, 0x0010 | dodatkowy status zgodny z defrostem | zgodny we wszystkich dostarczonych próbkach |
| R156 bit 11, 0x0800 | dodatkowy status zgodny z A4A | zgodny w próbkach; 8/8 zmian razem z A4A |
| R243L | Fact, Hz | istniejące dekodowanie |
| R244H | Fset, Hz | istniejące dekodowanie |

R156 miał wartości 0xC60C (defrost OFF, A4A OFF), 0xC61C (defrost ON, A4A OFF), 0xCE1C (defrost ON, A4A ON). Nie dowodzi identyczności flag w innych trybach/modelach. R144H=0x1A na postoju i przy pracy 0–80 Hz; 0x1B przy A4A ON. Nie nazywać pozostałego kodu fazą sprężarki.

R150H/R151H: kolejne inkrementacje 1→2→3→4→5→6 co ok. 60 min przy Fact=40 Hz, mimo defrostów; analogiczne przy 65 Hz. Przykład zakończenia: podczas pracy 3/3, na postoju 3/0, później 0/0. Czas opóźnienia zerowania nieznany. Nie są udowodnionymi licznikami całkowitej eksploatacji.

Źródła: [PyHaier](https://github.com/ktostam/PyHaier), [haier-monoblok-modbus](https://github.com/kmalysiak/haier-monoblok-modbus), [Elektroda, temat 3994059](https://www.elektroda.pl/rtvforum/topic3994059-30.html) (post #33 wskazujący liczniki godzin), [instrukcja serwisowa Super Aqua](https://haier-ac.pl/wp-content/uploads/materialy/instrukcje/pompy_ciepla/2023_haier_instrukcja_serwisowa_pompa_ciepla_super_aqua_co_cwu.pdf). Nie odnaleziono kompletnej potwierdzonej logiki załączenia A4A podczas defrostu. Odrębny alarm ochrony przeciwzamrożeniowej nie dowodzi progu grzałki podczas odszraniania.

## 6. A4A podczas defrostu — dane i hipotezy

Register Watch: 51 zachowanych zdarzeń, 41 par przed/po w chwili audytu. Zdarzenia wyselekcjonowane, czas przed/po to znacznik zdarzenia, nie dokładny czas obu ramek. Nie dowodzą braku krótkich impulsów.

Cztery zaobserwowane przejścia A4A OFF→ON, zawsze podczas defrostu, Fact=80 Hz. A04=0 we wszystkich dostarczonych próbkach.

| Próbka | Two przed → po, °C | Twi po, °C | Fact przed → po | Fset przed → po |
|---|---|---:|---|---|
| A | 29,7 → 28,5 | 30,5 | 80→80 | 39→80 |
| B | 30,3 → 29,4 | 33,9 | 80→80 | 80→80 |
| C | 29,6 → 28,6 | 30,2 | 80→80 | 49→80 |
| D | 29,0 → 26,9 | 30,3 | 80→80 | 80→80 |

W trzech cyklach ze znanym początkiem odstęp do zaobserwowanego A4A ON ok. 60, 91 i 121 s. A4A OFF następowało przy Fact=30 Hz, z Two odpowiednio 23,2 / 26,5 / 23,4 / 28,9°C (ostatnia próbka już po zakończeniu defrostu). Fset po zmianie 56 / 47 / 50 / 30 Hz. Temperatura nie wróciła wcześniej do zadanej.

Kontrprzykłady: w defrostach bez zaobserwowanego A4A ON zanotowano Two 27,0 / 24,0 / 26,9 / 26,4°C przy Fact=30 Hz. Był też Fact=80 Hz bez A4A. Ani Two <30°C, ani 80 Hz nie stanowią osobno potwierdzonego warunku. Zbyt rzadkie dane nie wykluczają krótkiego ON między próbkami.

**Hipoteza:** spadająca Two w okolicy 30°C w określonej fazie defrostu, możliwe dodatkowe opóźnienie. Wyłączenie koreluje z końcem zasadniczej fazy odszraniania, nie z osiągnięciem zadanej Two. To nie jest udowodniony algorytm. Nie zmieniać fabrycznego sterowania grzałką.

## 7. Rejestrator i dalszy plan

- `DefrostTrace`: pasywne próbki nie częściej niż co 5 s i tylko po zmianie wszystkich trzech potrzebnych banków; rzeczywisty odstęp może być dłuższy. Minuta historii przed i po, 16 ostatnich śladów, maks. 256 próbek/ślad i 2 MiB. Luki >30 s i nieznany początek oznaczają niepełny zapis. Brak dodatkowego ruchu RS485 i wpływu na sterowanie. Zapis zakończonych śladów co najmniej 300 s od poprzedniego zapisu, w ramach cyklicznej pętli; aktywny ślad w RAM.
- Plik lokalny `/opt/haier/.adaptive-defrost-trace-v1.json`. [defrost-trace-report.py](../tools/defrost-trace-report.py) eksportuje CSV za pomocą lokalnej biblioteki PyHaier. Nie publikować pełnych prywatnych śladów automatycznie.
- Statystyki pełnych obserwowanych defrostów w raporcie: A4A ON zaobserwowane / ON niezaobserwowane / niepełne dane A4A; mediana czasu, obserwowany czas ON (dolna granica), czas powrotu do CO. Obecnie RAM, od restartu. Nie są pomiarem poboru energii.
- Dalsze badania: porównać pełne ślady z A4A ON i bez ON, wyrównać względem początku defrostu, sprawdzić Two/Twi, różnicę temperatur, Tdef, Tao, Fact/Fset, czas i tempo spadku. Poszukać kontrprzykładów dla każdej hipotezy. Zbierać dane bez ręcznego wymuszania grzałki.
- Kolejne priorytety: rzeczywisty odbiór działania rejestratora, kontynuacja Experiment, trwały model cieplny budynku, porównanie kontekstów oraz diagnostyka odstępstw limitów. Nowe hipotezy rejestrów pozostają tylko do odczytu.

## 8. Jak kontynuować po utracie czatu

Najpierw przeczytaj ten dokument i aktualny README, sprawdź HEAD gałęzi i CI. Pobierz świeże dane z urządzenia; nie zakładaj, że stary stan eksperymentu nadal obowiązuje. Każda zmiana kodu: testy, commit, weryfikacja CI, instalacja z przypiętym SHA, odbiór na pompie. Zachowuj wyniki kolejnych badań tutaj z datą, wersją kodu, metodą, ograniczeniami i kontrprzykładami. W razie sprzeczności nowa obserwacja ma pierwszeństwo przed starą hipotezą; nie przepisuj hipotezy jako pewnika.
