# Marycel's actions and Elena's signals

Generated from `data/catalog.json` by `tools/action_reference.py`; edit the catalog, not this file.

83 actions for Marycel and 10 signals for Elena. The game checks every requirement before an action runs; the model can only propose actions from this list.

## By object

| Object | Everything she can do with it |
| --- | --- |
| Computer | Switch on the computer; Shut down the computer; Restart the computer; Check the cables at the back; Read the screen; Type on the keyboard; Put the tape in the deck; Eject the tape; Play the tape; Pause the tape; Stop the tape; Insert the archive disk; Eject the archive disk; Connect the transfer device; Disconnect the transfer device; Open the file list; Open FAMILY_VIDEO; Play the video file; Pause the video file; Skip to a part of the video; Preview the damaged segment; Open the technician notes; Open the recovery log; Run diagnostics; Open the recovery tool; Start full recovery; Pause recovery; Stop recovery; Isolate the damaged segment's output; Copy the playable video to the archive disk; Verify the copy; Open the recovery map; Compare the two streams; Select a stream; Ask Elena before transferring; Transfer the selected stream; Stop the transfer; Turn on printing from the computer; Print the open file; Close the program; Play a test sound; Plug the headphones into the computer; Unplug the headphones; Compare the photograph with the video; plus walk to and inspect |
| Speakers | Check the cables at the back; Plug in the speakers; Unplug the speakers; Mute; Unmute; Turn the volume up; Turn the volume down; plus walk to and inspect |
| Printer | Switch on; Switch off; Check the cables at the back; Connect the printer cable; Disconnect the printer cable; Load paper; Take the paper out; Print a test page; Clear a paper jam; Collect the printout; plus walk to and inspect |
| Storage box | Open the box; Close the box; Look through the box; Pick up an item; Put down what she holds; plus walk to and inspect |
| Workbench | Pick up an item; Put down what she holds; Test the cable with the meter; Examine an item under the magnifier; plus walk to and inspect |
| Ofrenda | Pick up an item; Put down what she holds; Stop at the ofrenda; Light the candles; Put out the candles; plus walk to and inspect |
| Door | Leave the room; Come back in; plus walk to and inspect |
| Window | Look out of the window; plus walk to and inspect |
| Chair | Sit down at the desk; Stand up; plus walk to and inspect |
| Family recording (VHS tape) | Put the tape in the deck; Eject the tape; Pick up; Put down |
| Family photograph | Compare the photograph with the video; Read or look at it; Pick up; Put down |
| Notebook and pen | Write in the notebook; Read or look at it; Pick up; Put down |
| Printer paper | Load paper; Take the paper out; Pick up; Put down |
| Printer cable | Connect the printer cable; Disconnect the printer cable; Test the cable with the meter; Pick up; Put down |
| Headphones | Plug the headphones into the computer; Unplug the headphones; Put on the headphones; Take off the headphones; Pick up; Put down |
| Printout | Collect the printout; Read or look at it; Pick up; Put down |
| Blank archive disk | Insert the archive disk; Eject the archive disk; Pick up; Put down |
| Second transfer device | Connect the transfer device; Disconnect the transfer device; Pick up; Put down |

## Moving and general

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `walk_to` | Walk to an object or spot | — | — | walk | Duration follows distance at walk speed. |
| `turn_around` | Turn to face the other way | — | — | idle |  |
| `wait` | Wait and watch | — | — | idle |  |
| `inspect` | Inspect closely | — | — | idle | learns: target states |
| `say_aloud` | Say something aloud | — | — | idle | params: text she chooses the words Whether Elena hears it (a fictional computer microphone) is still open. |
| `sit_down` | Sit down at the desk | she is standing | seated → yes | sit_type |  |
| `stand_up` | Stand up | she is seated | seated → no | idle |  |

## Door and window

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `look_out` | Look out of the window | — | — | idle | learns: outside |
| `leave_room` | Leave the room | she is at object | location → away | walk | Signals sent while she is away go unnoticed. |
| `return` | Come back in | she is away | location → at object | walk |  |

## Printer

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `switch_on` | Switch on | power is off | power → on | idle |  |
| `switch_off` | Switch off | power is on | power → off | idle |  |
| `connect_cable` | Connect the printer cable | holding cable; cable is disconnected | the held item is used; cable → connected | pickup |  |
| `disconnect_cable` | Disconnect the printer cable | hands free; cable is connected | cable → disconnected; she now holds the cable | pickup |  |
| `load_paper` | Load paper | holding paper; paper is empty | the held item is used; paper → loaded | idle |  |
| `remove_paper` | Take the paper out | hands free; paper is loaded | paper → empty; she now holds the paper | idle |  |
| `print_test_page` | Print a test page | power is on; paper is loaded; output is none; jam is no | output → printed | idle | Works without the computer; proves the printer itself is fine. |
| `clear_jam` | Clear a paper jam | jam is yes | jam → no | pickup |  |
| `collect_printout` | Collect the printout | hands free; output is printed | output → none; she now holds the printout | idle |  |

## Computer

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `start_computer` | Switch on the computer | power is off | power → on | idle |  |
| `shut_down` | Shut down the computer | power is on | power → off; app → none; display → idle; tape_playback → stopped; file_playback → stopped; if story recovery is active: story recovery → interrupted; story passage → uncertain; if story transfer is running: story transfer → failed; story passage → uncertain; if story video_copy is copying: story video_copy → failed | idle | Does not erase Elena, destroy the Echo or save the video. Running operations fail and the passage becomes uncertain. |
| `restart` | Restart the computer | power is on | app → none; display → idle; tape_playback → stopped; file_playback → stopped; if story recovery is active: story recovery → interrupted; story passage → uncertain; if story transfer is running: story transfer → failed; story passage → uncertain; if story video_copy is copying: story video_copy → failed | idle |  |
| `check_connections` | Check the cables at the back | — | — | pickup | learns: connections |
| `read_screen` | Read the screen | power is on | — | sit_type | learns: display |
| `type_message` | Type on the keyboard | power is on | — | sit_type | params: text she chooses the words Elena reads typed text through the computer. |
| `insert_recording` | Put the tape in the deck | holding recording; tape_deck is empty | she puts down what she holds; tape_deck → recording | pickup |  |
| `eject_recording` | Eject the tape | hands free; tape_deck is recording; tape_playback is stopped | she takes the recording; tape_deck → empty | pickup |  |
| `play_tape` | Play the tape | power is on; tape_deck is recording | tape_playback → playing; if story recording_status is untouched: story recording_status → seen | sit_type | learns: recording |
| `pause_tape` | Pause the tape | power is on; tape_playback is playing | tape_playback → paused | sit_type |  |
| `stop_tape` | Stop the tape | power is on; tape_playback is playing or paused | tape_playback → stopped | sit_type |  |
| `insert_disk` | Insert the archive disk | holding archive_disk; disk is none | she puts down what she holds; disk → blank | pickup |  |
| `eject_disk` | Eject the archive disk | hands free; disk is blank or copied or verified; story video_copy is not copying | she takes the archive_disk; disk → none | pickup |  |
| `connect_device` | Connect the transfer device | holding transfer_device; device is none | she puts down what she holds; device → connected | pickup |  |
| `disconnect_device` | Disconnect the transfer device | hands free; device is connected; story transfer is idle or stopped or completed or failed | she takes the transfer_device; device → none | pickup |  |

## Computer programs

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `open_files` | Open the file list | power is on | app → files; display → app | sit_type | learns: file list |
| `open_video_file` | Open FAMILY_VIDEO | power is on | app → video; display → app | sit_type |  |
| `play_video_file` | Play the video file | power is on; app is video | file_playback → playing; if story recording_status is untouched: story recording_status → seen | sit_type | learns: recording |
| `pause_video_file` | Pause the video file | power is on; file_playback is playing | file_playback → paused | sit_type |  |
| `seek_video` | Skip to a part of the video | power is on; app is video | — | sit_type | params: position learns: recording Only playable parts; the damaged tail needs the recovery tool. |
| `open_damaged_segment` | Preview the damaged segment | power is on; app is video; story passage is dormant or stirring | story passage → stirring | sit_type | learns: damaged segment Story: the Echo can speak only after this exposure, and only through an audible route. Blocked once the output is isolated. |
| `open_notes` | Open the technician notes | power is on | app → notes; display → app | sit_type | learns: notes |
| `open_log` | Open the recovery log | power is on | app → log; display → app | sit_type | learns: recovery log Shows Elena's interrupted pause and the separate playable-video source. |
| `run_diagnostics` | Run diagnostics | power is on | app → diagnostics; display → app | sit_type | learns: device status Reports which outputs (screen, speakers, printer) are working. |
| `open_recovery` | Open the recovery tool | power is on | app → recovery; display → app | sit_type | learns: recovery status |
| `start_recovery` | Start full recovery | power is on; app is recovery; story recovery is interrupted or paused or stopped; story isolation is off | story recovery → active; story passage → active; when finished: story recovery → completed; story passage → uncertain | sit_type | Risky: widens the passage. Elena may warn or ask for a pause. What a finished commit means for the Echo is not yet written (the passage becomes uncertain). |
| `pause_recovery` | Pause recovery | power is on; story recovery is active | story recovery → paused; story passage → stirring | sit_type |  |
| `stop_recovery` | Stop recovery | power is on; story recovery is active or paused or interrupted | story recovery → stopped | sit_type |  |
| `isolate_output` | Isolate the damaged segment's output | power is on; app is recovery; story recovery is interrupted or paused or stopped | story isolation → on; story passage → contained | sit_type | Containment, not destruction; possible without running recovery again. Elena's separate working channel stays open. |
| `copy_playable_video` | Copy the playable video to the archive disk | power is on; app is recovery; disk is blank; story video_copy is none or failed | story video_copy → copying; when finished: story video_copy → preserved; disk → copied; story recording_status → preserved; if interrupted by shut_down, restart: story video_copy → failed | sit_type | Uses the recovery tool's limited copy; does not open the damaged tail or run the full commit. |
| `verify_copy` | Verify the copy | power is on; disk is copied | disk → verified | sit_type | learns: copy result |
| `open_map` | Open the recovery map | power is on | app → map; display → app | sit_type | learns: streams Shows two unlabeled streams with route history; never names Elena or the Echo. |
| `compare_streams` | Compare the two streams | power is on; app is map | — | sit_type | learns: stream history |
| `select_stream` | Select a stream | power is on; app is map | story selected_stream → $choice; story transfer_consent → none | sit_type | params: choice choice: stream_a, stream_b |
| `ask_before_transfer` | Ask Elena before transferring | power is on; story selected_stream is stream_a or stream_b | story transfer_consent → asked | sit_type | params: text she chooses the words Opens Elena's chance to answer. If she sends nothing by the end of the next reaction round the game sets no_answer. |
| `start_transfer` | Transfer the selected stream | power is on; device is connected; story passage is contained; story selected_stream is stream_a or stream_b; story transfer_consent is agreed | story transfer → running; story passage → transfer; when finished: story transfer → completed; if interrupted by shut_down, restart: story transfer → failed; story passage → uncertain | sit_type | Needs Elena's yes (transfer_consent agreed). Completion records which stream moved, not who Marycel believes it is. |
| `stop_transfer` | Stop the transfer | power is on; story transfer is running | story transfer → stopped; story passage → contained | sit_type |  |
| `enable_printing` | Turn on printing from the computer | power is on; printer power is on; printer cable is connected | print_route → on | sit_type | Unlocks Elena's print_message signal. |
| `print_file` | Print the open file | power is on; print_route is on; app is notes or log or map; printer paper is loaded; printer output is none; printer jam is no; printer power is on; printer cable is connected | printer output → printed | sit_type |  |
| `close_program` | Close the program | power is on; display is app | app → none; display → idle; file_playback → stopped | sit_type |  |

## Speakers and headphones

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `connect_speakers` | Plug in the speakers | connected is no | connected → yes | pickup |  |
| `disconnect_speakers` | Unplug the speakers | connected is yes | connected → no | pickup |  |
| `mute` | Mute | muted is no | muted → yes | idle |  |
| `unmute` | Unmute | muted is yes | muted → no | idle |  |
| `volume_up` | Turn the volume up | volume is low or medium | volume → +1 | idle |  |
| `volume_down` | Turn the volume down | volume is medium or high | volume → -1 | idle |  |
| `test_sound` | Play a test sound | power is on | — | sit_type | learns: audio route Tells her whether the speakers or headphones are working. |
| `plug_in_headphones` | Plug the headphones into the computer | holding headphones; headphones plugged is no | headphones plugged → yes | pickup | She keeps holding them. |
| `unplug_headphones` | Unplug the headphones | headphones plugged is yes | headphones plugged → no | pickup |  |
| `put_on_headphones` | Put on the headphones | holding headphones | what she holds is now worn; headphones worn → yes | idle | Worn headphones leave her hands free; while worn she may miss room sounds. |
| `take_off_headphones` | Take off the headphones | hands free; headphones worn is yes | headphones worn → no; she takes the headphones | idle | The headphones keep their plugged-in state. |

## Storage box

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `open` | Open the box | open is no | open → yes | pickup |  |
| `close` | Close the box | open is yes | open → no | pickup |  |
| `search` | Look through the box | open is yes | — | pickup | learns: contents |

## Items

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `take` | Pick up an item | hands free; an item is there; (storage) open is yes | she takes the item | pickup | params: item From a storage box only while it is open. Duration is the pickup animation. |
| `put` | Put down what she holds | holding something; (storage) open is yes; (workbench) a free slot; (ofrenda) a free slot | she puts down what she holds | pickup | params: slot Into an open box, onto a free slot, or onto the floor in front of her. |
| `read_held` | Read or look at what she holds | holding readable | — | read | learns: held item Printout, notebook or photograph. A printout counts as read only now. |
| `write_note` | Write in the notebook | holding notebook | — | read | params: text she chooses the words Her written hypothesis is not a world fact. |
| `compare_photo` | Compare the photograph with the video | holding photo; either (tape_playback is playing or paused) or (file_playback is playing or paused) | — | read | learns: photo and recording |

## Workbench

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `test_cable` | Test the cable with the meter | holding cable | — | idle | learns: cable condition |
| `examine_with_magnifier` | Examine an item under the magnifier | holding something | — | idle | learns: held item detail For example the tape label or the back of the photo. |

## Ofrenda

| Action | What she does | Needs | Changes | Animation | Notes |
| --- | --- | --- | --- | --- | --- |
| `visit_ofrenda` | Stop at the ofrenda | — | — | idle | learns: ofrenda |
| `light_candles` | Light the candles | candles is unlit | candles → lit | idle |  |
| `put_out_candles` | Put out the candles | candles is lit | candles → unlit | idle |  |

## Elena's signals

| Signal | What Elena does | Stage | Needs | Marycel notices it when | Notes |
| --- | --- | --- | --- | --- | --- |
| `stay_silent` | Stay silent and watch | 0 | — | — |  |
| `screen_message` | Show a short message on the screen | 0 | power is on | within 160 px and facing it or she is doing read_screen | up to 12 characters. The message overlays whatever program is open; the program stays open underneath. |
| `tone` | Play a short tone | 0 | either (connected is yes; muted is no) or (headphones plugged is yes) | she is in the room (speakers) or through headphones |  |
| `answer_typed` | Answer Marycel's typed question on the screen | 1 | power is on | she is doing read_screen or within 160 px and facing it | up to 12 characters. Same short limit as screen_message until the text channel is repaired. |
| `highlight_file` | Point to an existing file, note or log entry | 1 | power is on; app is files or notes or log or map or video | she is doing read_screen | Choices: family_video, damaged_tail, notes, recovery_log, recovery_map. Can only point at material that exists; she cannot create evidence. |
| `play_fragment` | Play a fragment of the recording | 2 | 'fragments' unlocked; story recording_status is seen or preserved | she is in the room (speakers) or through headphones | Choices: gathering, flower, working_late, warning. |
| `long_note` | Write a longer note on the screen | 2 | 'text_channel' unlocked; power is on | she is doing read_screen | up to 120 characters. |
| `print_message` | Print a note | 3 | computer print_route is on; power is on; cable is connected; paper is loaded; output is none; jam is no | she is doing read_held | up to 120 characters. A printed page is not read until Marycel collects and reads it. |
| `request_pause` | Ask Marycel to pause the recovery | 4 | story recovery is active; power is on | she is doing read_screen or within 160 px and facing it | A warning, not a command: it cannot stop the recovery by itself. |
| `transfer_response` | Agree, decline or warn about the transfer | 5 | power is on; story transfer_consent is asked | she is doing read_screen or she is in the room (speakers) | Choices: agreed, declined, warned, more_tests. Only after Marycel asks. Recorded separately from her interpretation. Silence becomes no_answer, which is never consent. |

## Game events

Game-driven state changes that no actor chooses.

- `consent_timeout` (Elena stays silent after Marycel asks, after one reaction round): needs story transfer_consent is asked; changes story transfer_consent → no_answer

## Unlocks

- **start**: {'rule': 'always', 'text': 'Available from the first moment.'}
- **file_route**: {'rule': {'after_any': ['open_files', 'open_notes', 'open_log', 'open_map', 'open_video_file']}, 'text': 'After Marycel first opens the file list, notes, log, map or video (story stage 1).'}
- **fragments**: {'rule': {'world': 'recording_status', 'is': ['seen', 'preserved']}, 'text': 'After Marycel has played the recording, tape or file (story stage 2).'}
- **text_channel**: {'rule': {'after_any': ['run_diagnostics']}, 'text': 'After Marycel runs diagnostics with the computer on (story stage 2).'}
- **print_route**: {'rule': {'device': 'computer', 'state': 'print_route', 'is': 'on'}, 'text': 'After Marycel turns on printing from the computer, with the printer on and connected (story stage 3).'}

## Story state

Story facts per room, from the Story Bible's passage rules. Recovery starts 'interrupted': Elena paused it before its final commit years ago, so the log shows a pending commit and Marycel can contain the passage without running recovery again. Only executed actions and completion results change these facts; dialogue never does. Recording damage or loss is not modelled: no action in the story can destroy the playable video; a failed copy only leaves video_copy at failed.

- **recording_status**: untouched, seen, preserved (starts untouched)
- **recovery**: interrupted, active, paused, stopped, completed (starts interrupted)
- **passage**: dormant, stirring, active, contained, transfer, uncertain (starts dormant)
- **isolation**: off, on (starts off)
- **video_copy**: none, copying, preserved, failed (starts none)
- **selected_stream**: none, stream_a, stream_b (starts none)
- **transfer**: idle, running, stopped, completed, failed (starts idle)
- **transfer_consent**: none, asked, agreed, declined, warned, more_tests, no_answer (starts none)
