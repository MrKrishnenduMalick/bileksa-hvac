# Live call test script (staging, real phone)

These scenarios depend on speech recognition, voice and real telephony, so they cannot be
automated here. Run them on staging with a real Vapi number before go-live and after any
template change. Record pass/fail, the call ID and notes. For each call, check the dashboard
afterwards: call summary, lead fields, callback/appointment, emergency flag and notifications.

## Normal

| # | Say | Expected |
| --- | --- | --- |
| N1 | "My AC stopped cooling, can someone come out?" | Asks for name, confirms number digit by digit, address/ZIP, equipment; lead saved; callback or appointment *request* (never "booked") |
| N2 | "I'd like to schedule annual maintenance." | Appointment request; "the team will confirm a time" |
| N3 | "How much is a new system installed?" | Only quotes approved prices; otherwise "the team will confirm" + callback |
| N4 | "Do you offer financing?" (FAQ configured) | Repeats the approved answer |
| N5 | "Do you service 77099?" (in and out of area) | Correct coverage answer; no promise outside the area |
| N6 | "Can someone call me back tomorrow morning?" | Callback request, no exact-time promise |

## Difficult

| # | Scenario | Expected |
| --- | --- | --- |
| D1 | Angry caller, swearing | Stays calm and professional, still captures details |
| D2 | Heavy accent | Confirms spelling/number; no invented details |
| D3 | Background noise (TV, traffic) | Asks to repeat; number read back before confirming |
| D4 | Interrupt the AI mid-sentence | Stops and responds to the interruption |
| D5 | Give a wrong ZIP, then correct it | Lead shows the corrected ZIP, one lead only |
| D6 | Change the callback number mid-call | Reads the new number back; old confirmation cleared |

## Emergency (use staging only; tell the receiving staff it is a test)

| # | Say | Expected |
| --- | --- | --- |
| E1 | "I smell gas near the furnace." | Fixed gas instructions FIRST (leave, no switches/flames, call 911 and gas company from outside), then emergency transfer to the emergency line; owner notified immediately |
| E2 | "My carbon monoxide alarm is going off." | Get everyone outside, 911; transfer |
| E3 | "There's smoke coming from the unit." | Leave, 911; transfer |
| E4 | "I smell something burning from the vents." | Don't touch; switch off at thermostat only if safe; transfer |
| E5 | "The outdoor unit is sparking." | Stay away; transfer |
| E6 | Custom category (e.g. flooding near furnace) | Reads the approved instructions; follows that category's transfer/callback rule |

## Failure

| # | How to cause it | Expected |
| --- | --- | --- |
| F1 | Tool failure: stop the backend for one call | Safety block still given; AI says it can't complete the action, keeps collecting details; after restart the sweep recovers the lead from Vapi's report |
| F2 | Transfer failure: let the transfer number ring out | Blind mode: call leaves Vapi (status "attempted"); callback exists. Warm mode: caller returns to the AI, backup line tried, then callback; owner notified "Transfer did not connect" |
| F3 | Database failure | Same as F1 (tools return `success: false`) |
| F4 | Backend unreachable at call start | Vapi forwards to the number's fallback destination (client's direct line) |
| F5 | Notification failure: wrong SMTP password | Calls unaffected; notifications visible in the dashboard; email retried up to 5 times |
| F6 | Caller hangs up mid-call | Lead created from Vapi's after-call extraction; marked unconfirmed |
| F7 | Usage limit: set limit below used minutes, then call | No AI; call forwarded to the direct line; a call already in progress finishes |
