# Delayed ACK test correction

The original RED reached disabled Send while A's genuine ACK was held. The shared sending flag incorrectly covered B. Production now stores in-flight submission by conversation. The first GREEN and debug runs progressed through successful B admission and real native completion, but the test selected A at the final assertion: it read the selected conversation identifier before asynchronous “New conversation” completed.

Debug v1 actual DB states were A interrupted/user_stop/graph_started=False and B completed/graph_started=True; the displayed history was A. This is a test-wait defect, not lack of native B completion. The test now waits for two actual conversation rows before capturing selected B and asserts B differs from A. Failed logs remain intact. The next integrated focused run determines the complete corrected scenario result; no test output was mocked or expectation weakened.
