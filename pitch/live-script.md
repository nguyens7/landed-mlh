# Live pitch script (spoken, ~2:40 at 150 wpm)

Rehearse with a timer. Target under 3:00. Word count is in the last line.

**[Slide 1]** January 29, 2025. Washington, DC. An Army Black Hawk and an American Eagle jet collided on short final to Reagan National. Sixty-seven people died. One controller was working the combined local and helicopter position. The two aircraft were on different frequencies and could not hear each other. A conflict alert had been active for about twenty-six seconds. The NTSB cited inadequate traffic advisories and the lack of safety alerts to both crews.

**[Slide 2]** Here in New York, helicopters fly the Hudson and East River routes below the Class B, announcing themselves on a shared frequency. No controller is required to listen. Controllers get pulled in when a helicopter heads toward LaGuardia's airspace, sometimes on a position that is also working the runway. A commenter on r/ATC put it well: medevac helicopters not crossing arrival or departure paths are a repetitive, low risk task, and a good first trial for AI.

**[Slide 3]** That is Landed. On a simulated desk, Landed handles routine medevac check-ins and hands anything risky to the controller. It flags trouble early. The human makes every hard call. Think highway driver assist: it handles the long boring stretch and says take the wheel before the hard interchange. It is a simulation. It never transmits.

**[Slide 4]** This is real traffic: seventeen helicopters from last Saturday morning, replayed from public ADS-B data. Now a simulated medevac lifts off and heads up the East River at six hundred feet toward College Point. Its path will cross LaGuardia's runway twenty-two final, about one mile out. Landed projects ninety seconds ahead and raises an alert about eighty-four seconds before entry, with a plain English reason and a countdown. The controller acknowledges or takes over. A DCA-like situation, caught early. And in an emergency, Landed says one line and goes silent. The human owns the frequency.

**[Slide 5]** Trust is the product. Every alert carries a reason and a confidence score. The voice agent we are building picks from a fixed phrase list and never makes up words. Anything uncertain goes to the controller.

**[Slide 6]** Gemini transcribes each radio call, parses it into structured data with a confidence, picks the reply template, and speaks the exact approved text.

**[Slide 8]** Next: harden the voice agent, replace our approximate geometry with exact legal boundaries, and measure false alarms across many days. Landed is designed to raise an earlier alert, but nobody has tested what would have happened at DCA. Takes the routine. Flags trouble early. The human makes every hard call.

(Slide 7, prior art, is shown but not read.)

Words: ~410.
