// The Java entry point: one line hands control to the project's jar.
// HybridApp.start() builds the whole graph in Java and returns the tables to publish.
import com.acme.hybrid.HybridApp

def app = io.deephaven.appmode.ApplicationContext.get()
HybridApp.start().each { name, table -> app.setField(name, table) }
